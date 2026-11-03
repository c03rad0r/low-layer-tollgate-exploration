"""Four-state link session: unpaid -> paid -> grace -> evicted.

Pause, do not drop. `grace` is only meaningful if the link and the payment lane
stay open; `Session` models that, and `gate.FipsGate` refuses to pretend FIPS can
implement it today.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class State(str, Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    GRACE = "grace"
    EVICTED = "evicted"


class SessionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Notice:
    code: str
    level: str
    session_id: str
    retry_after: Optional[int] = None
    top_up: Optional[int] = None


@dataclass
class Session:
    npub: str
    rate_bytes_per_msat: Decimal
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    state: State = State.UNPAID
    allotment_msat: Decimal = Decimal(0)
    used_msat: Decimal = Decimal(0)
    issued_at_mono: float = field(default_factory=time.monotonic)
    admission_seconds: float = 30.0
    grace_seconds: float = 30.0
    max_session_seconds: Optional[float] = None
    valid_until_mono: Optional[float] = None
    grace_deadline_mono: Optional[float] = None
    evicted_reason: Optional[str] = None
    last_notice_at_mono: Optional[float] = None

    def __post_init__(self) -> None:
        if self.rate_bytes_per_msat <= 0:
            raise SessionError("rate must be positive")
        self.rate_bytes_per_msat = Decimal(self.rate_bytes_per_msat)

    # -- derived ---------------------------------------------------------

    @property
    def remaining_msat(self) -> Decimal:
        return max(Decimal(0), self.allotment_msat - self.used_msat)

    @property
    def deadline_mono(self) -> Optional[float]:
        """The session's absolute deadline, in monotonic seconds.

        FIPS has no time sync, so a monotonic local timer is the authority.
        `valid_until` is the cross-check that lets a restarted seller rebuild
        state; it is not allowed to extend the local deadline.
        """
        candidates = []
        if self.max_session_seconds is not None:
            candidates.append(self.issued_at_mono + self.max_session_seconds)
        if self.valid_until_mono is not None:
            candidates.append(self.valid_until_mono)
        return min(candidates) if candidates else None

    @property
    def forwarding_allowed(self) -> bool:
        return self.state is State.PAID

    @property
    def payment_lane_open(self) -> bool:
        return self.state is not State.EVICTED

    @property
    def link_open(self) -> bool:
        return self.state is not State.EVICTED

    # -- transitions -----------------------------------------------------

    def pay(self, msat: Decimal, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        msat = Decimal(msat)
        if msat <= 0:
            raise SessionError("payment must be positive")
        if self.state is State.EVICTED:
            raise SessionError("cannot pay an evicted session; re-admit first")
        self.allotment_msat += msat
        if self.state in (State.UNPAID, State.GRACE):
            self.state = State.PAID
            self.grace_deadline_mono = None
            self.evicted_reason = None
        # A payment after the absolute deadline re-arms it for one more local
        # window only if the caller explicitly re-admits; do not silently extend.

    def charge(self, nbytes: int, now: Optional[float] = None) -> Decimal:
        """Accrue the cost of `nbytes`. Returns the cost in msat.

        Only `paid` forwards, so only `paid` can be charged. Bytes offered in
        `unpaid` or `grace` are not forwarded and are not billed.

        The measurement step that crosses the boundary may push `used_msat`
        past `allotment_msat` by up to one step: one frame if metering per
        frame, one polling interval if counters are batched. Keep the step
        small; the seller absorbs the overshoot.
        """
        if nbytes < 0:
            raise SessionError("nbytes must be non-negative")
        if self.state is not State.PAID:
            return Decimal(0)
        now = time.monotonic() if now is None else now
        cost = Decimal(nbytes) / self.rate_bytes_per_msat
        self.used_msat += cost
        if self.allotment_msat > 0 and self.used_msat >= self.allotment_msat:
            self._enter_grace(now)
        return cost

    def tick(self, now: Optional[float] = None) -> State:
        now = time.monotonic() if now is None else now
        if self.state is State.EVICTED:
            return self.state

        deadline = self.deadline_mono
        if self.state is State.PAID and deadline is not None and now >= deadline:
            # The absolute deadline is reached. Renewal is still possible, so
            # move to grace rather than dropping the link.
            self._enter_grace(now)

        if self.state is State.UNPAID:
            if now >= self.issued_at_mono + self.admission_seconds:
                self._evict("admission timeout", now)
        elif self.state is State.GRACE:
            if self.grace_deadline_mono is None:
                self.grace_deadline_mono = now + self.grace_seconds
            if now >= self.grace_deadline_mono:
                self._evict("grace expired", now)
        return self.state

    def _enter_grace(self, now: float) -> None:
        if self.state is State.PAID:
            self.state = State.GRACE
            self.grace_deadline_mono = now + self.grace_seconds

    def _evict(self, reason: str, now: float) -> None:
        self.state = State.EVICTED
        self.evicted_reason = reason
        self.grace_deadline_mono = None

    # -- notices ---------------------------------------------------------

    def notice(self, now: Optional[float] = None) -> Optional[Notice]:
        now = time.monotonic() if now is None else now
        if self.state is State.EVICTED:
            return None
        if self.last_notice_at_mono is not None and now - self.last_notice_at_mono < 10:
            return None

        code = level = None
        retry_after = None
        top_up = None
        if self.state is State.UNPAID:
            code, level = "payment-required", "info"
            retry_after = 10
            top_up = max(1, math.ceil(self.allotment_msat))
        elif self.state is State.GRACE:
            code, level = "session-exhausted", "error"
            if self.grace_deadline_mono is not None:
                retry_after = max(1, math.ceil(self.grace_deadline_mono - now))
            top_up = max(1, math.ceil(self.allotment_msat - self.used_msat))
        elif self.state is State.PAID and self.allotment_msat > 0:
            if self.used_msat >= self.allotment_msat * Decimal("0.8"):
                code, level = "payment-due", "info"
                top_up = max(1, math.ceil(self.allotment_msat - self.used_msat))

        if code is None:
            return None
        self.last_notice_at_mono = now
        return Notice(
            code=code,
            level=level or "info",
            session_id=self.session_id,
            retry_after=retry_after,
            top_up=top_up,
        )
