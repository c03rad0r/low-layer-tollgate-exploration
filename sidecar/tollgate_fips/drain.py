"""Background settlement drain.

`SettlementWorker.settle_vault_batch` is a single pass. A seller runs it on a
timer, with backoff when the mint refuses:

    pass: redeem what the vault holds, settle the journal, release exposure
    no progress and failures -> exponential backoff, capped
    progress or nothing to do -> reset to the normal poll interval

A token the mint keeps refusing is retried `max_attempts` times, then
**dead-lettered**: parked in the vault for manual reconciliation instead of
being retried forever. `requeue(key)` puts it back after the cause is fixed.

`health()` is the operator surface: last pass, last success, last error,
consecutive failures, pending and dead-lettered counts. It is a plain dict /
dataclass so it can be exposed by an HTTP endpoint or a control socket.

The daemon is deliberately small and injectable (`clock`, `wall_clock`,
`sleep`, `stop`) so the loop can be tested without real time.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from .settlement import SettlementWorker, VaultSettlementResult
from .vault import TokenVault


@dataclass
class DrainStats:
    passes: int = 0
    settled: int = 0
    failed: int = 0
    fee_sat: int = 0
    errors: List[str] = field(default_factory=list)

    def add(self, result: VaultSettlementResult) -> None:
        self.passes += 1
        self.settled += result.settled
        self.failed += result.failed
        self.fee_sat += result.fee_sat
        self.errors.extend(result.errors)


@dataclass
class DrainHealth:
    passes: int = 0
    settled: int = 0
    failed: int = 0
    fee_sat: int = 0
    last_pass_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    pending: int = 0
    dead_lettered: int = 0
    backoff_seconds: float = 0.0
    max_attempts: int = 0

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


class SettlementDaemon:
    def __init__(self, vault: TokenVault, worker: SettlementWorker,
                 poll_seconds: float = 30.0, max_backoff_seconds: float = 300.0,
                 batch_size: int = 10, max_attempts: int = 10,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if max_backoff_seconds < poll_seconds:
            raise ValueError("max_backoff_seconds must be >= poll_seconds")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.vault = vault
        self.worker = worker
        self.poll_seconds = poll_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.batch_size = batch_size
        self.max_attempts = max_attempts
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.backoff = poll_seconds
        self._passes = 0
        self._settled = 0
        self._failed = 0
        self._fee_sat = 0
        self._last_pass_at: Optional[float] = None
        self._last_success_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._consecutive_failures = 0

    # -- one pass --------------------------------------------------------

    def run_once(self) -> VaultSettlementResult:
        result = self.worker.settle_vault_batch(self.vault,
                                                batch_size=self.batch_size)
        if result.failed_keys:
            counts = self.vault.record_attempts(result.failed_keys,
                                                now=self.wall_clock())
            dead = [key for key, attempts in counts.items()
                    if attempts >= self.max_attempts]
            if dead:
                result.dead_lettered = self.vault.mark_dead_letter(
                    dead, now=self.wall_clock())

        if result.failed > 0 and result.settled == 0:
            self.backoff = min(self.max_backoff_seconds, self.backoff * 2)
        else:
            # Progress, or nothing to do. An empty vault (including one with
            # only dead letters) is not a failure.
            self.backoff = self.poll_seconds
        self._record(result)
        return result

    def _record(self, result: VaultSettlementResult) -> None:
        self._passes += 1
        self._settled += result.settled
        self._failed += result.failed
        self._fee_sat += result.fee_sat
        self._last_pass_at = self.wall_clock()
        if result.settled > 0:
            self._last_success_at = self._last_pass_at
            self._consecutive_failures = 0
        elif result.failed > 0:
            self._consecutive_failures += 1
        if result.errors:
            self._last_error = result.errors[-1]
        elif result.settled > 0:
            self._last_error = None

    # -- loop ------------------------------------------------------------

    def run(self, stop: Optional[Callable[[], bool]] = None,
            max_passes: Optional[int] = None) -> DrainStats:
        """Drain until `stop()` or `max_passes`.

        The first pass runs immediately; afterwards the loop sleeps the current
        backoff.
        """
        stop = stop or (lambda: False)
        stats = DrainStats()
        while not stop():
            stats.add(self.run_once())
            if max_passes is not None and stats.passes >= max_passes:
                break
            if stop():
                break
            self.sleep(self.backoff)
        return stats

    # -- operator surface ------------------------------------------------

    def health(self) -> DrainHealth:
        counts = self.vault.counts()
        return DrainHealth(
            passes=self._passes,
            settled=self._settled,
            failed=self._failed,
            fee_sat=self._fee_sat,
            last_pass_at=self._last_pass_at,
            last_success_at=self._last_success_at,
            last_error=self._last_error,
            consecutive_failures=self._consecutive_failures,
            pending=counts["pending"],
            dead_lettered=counts["dead_lettered"],
            backoff_seconds=self.backoff,
            max_attempts=self.max_attempts,
        )

    def dead_letters(self, limit: int = 1000):
        return self.vault.dead_lettered(limit=limit)

    def requeue(self, key: str) -> bool:
        """Retry a dead letter on the next pass after the cause is fixed."""
        return self.vault.requeue(key)
