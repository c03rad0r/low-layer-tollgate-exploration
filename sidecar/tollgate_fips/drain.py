"""Background settlement drain.

`SettlementWorker.settle_vault_batch` is a single pass. A seller runs it on a
timer, with backoff when the mint refuses:

    pass: redeem what the vault holds, settle the journal, release exposure
    no progress and failures -> exponential backoff, capped
    progress -> reset to the normal poll interval

The daemon is deliberately small and injectable (`clock`, `sleep`, `stop`) so
the loop can be tested without real time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

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


class SettlementDaemon:
    def __init__(self, vault: TokenVault, worker: SettlementWorker,
                 poll_seconds: float = 30.0, max_backoff_seconds: float = 300.0,
                 batch_size: int = 10,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        if max_backoff_seconds < poll_seconds:
            raise ValueError("max_backoff_seconds must be >= poll_seconds")
        self.vault = vault
        self.worker = worker
        self.poll_seconds = poll_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.batch_size = batch_size
        self.clock = clock
        self.sleep = sleep
        self.backoff = poll_seconds

    def run_once(self) -> VaultSettlementResult:
        result = self.worker.settle_vault_batch(self.vault,
                                                batch_size=self.batch_size)
        if result.settled > 0:
            self.backoff = self.poll_seconds
        elif result.failed > 0:
            self.backoff = min(self.max_backoff_seconds, self.backoff * 2)
        return result

    def run(self, stop: Optional[Callable[[], bool]] = None,
            max_passes: Optional[int] = None) -> DrainStats:
        """Drain until `stop()` or `max_passes`.

        The first pass runs immediately; afterwards the loop sleeps the current
        backoff. An empty vault counts as a successful pass and resets backoff.
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
