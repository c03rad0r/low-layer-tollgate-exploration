"""Seller controller: session state in, gate actions out.

The demos drive the gate step by step. This is the loop a real seller runs:

    tick():
      session.tick()                 # deadlines / grace / eviction
      paid   -> resume forwarding if paused
      grace  -> pause forwarding (transit blocked, link kept)
      evicted-> durable evict, then an optional L0 frame block
      paid   -> meter, charge, and pause when the charge crosses the boundary

Metering is frozen while not `paid`: the baseline snapshot is advanced without
charging, so a paused peer's refused transit is never billed when it resumes.
The policy-drop delta is subtracted from the same window (`meter.delta`), which
covers frames the gate dropped between ticks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .gate import FipsGate, PauseResult
from .frame_gate import FrameGateError
from .meter import LinkCounters, delta, snapshot
from .session import Session, State


class ControllerError(RuntimeError):
    pass


@dataclass
class ControllerConfig:
    rate_bytes_per_msat: Decimal
    grace_seconds: float = 30.0
    tick_seconds: float = 0.25


@dataclass
class ControllerResult:
    state: str
    actions: List[str] = field(default_factory=list)
    billable_bytes: int = 0
    charged_msat: Decimal = Decimal(0)
    paused: bool = False
    evicted: bool = False
    frame_blocked: bool = False


class SellerController:
    def __init__(self, gate: FipsGate, session: Session,
                 config: Optional[ControllerConfig] = None,
                 frame_gate=None, mac: Optional[str] = None):
        if frame_gate is not None and not mac:
            raise ControllerError("frame_gate requires the session's source MAC")
        self.gate = gate
        self.session = session
        self.frame_gate = frame_gate
        self.mac = mac
        self.config = config or ControllerConfig(
            rate_bytes_per_msat=session.rate_bytes_per_msat,
            grace_seconds=session.grace_seconds,
        )
        self.paused = False
        self.evicted = False
        self.frame_blocked = False
        self._previous: Optional[Dict[Any, LinkCounters]] = None
        self._previous_policy: int = 0

    # -- metering --------------------------------------------------------

    def _snapshot(self):
        current = snapshot(self.gate.fipsctl.peers(), self.gate.fipsctl.links())
        policy = self.gate.policy_blocked_for(self.session.npub)["bytes"]
        return current, policy

    def _reset_baseline(self) -> None:
        self._previous, self._previous_policy = self._snapshot()

    # -- main loop -------------------------------------------------------

    def tick(self, now: Optional[float] = None) -> ControllerResult:
        now = time.monotonic() if now is None else now
        state = self.session.tick(now)
        actions: List[str] = []
        charged = Decimal(0)
        billable = 0

        # Resume before metering so the tick that pays can also charge.
        if state is State.PAID and self.paused:
            self.gate.resume(self.session.npub)
            self.paused = False
            actions.append("resume")

        if state is State.GRACE and not self.paused:
            result: PauseResult = self.gate.pause(self.session.npub)
            self.paused = True
            actions.append(f"pause:{result.mode}")

        if state is State.EVICTED and not self.evicted:
            result = self.gate.evict(self.session.npub)
            self.evicted = True
            actions.append(f"evict:{result.mode}")
            # L0 drop follows the durable eviction (deny -> ACL -> disconnect),
            # never the other way round: the link gate is the authorisation
            # boundary, and dropping first would destroy the evidence a grace
            # or unpaid session needs to resume. Only for sellers that opted
            # into a frame gate with an out-of-band checkout path.
            if self.frame_gate is not None:
                try:
                    self.frame_gate.block(self.mac)
                except FrameGateError:
                    # The link eviction already succeeded; L0 is advisory and
                    # must not make it look like eviction failed.
                    actions.append("frame-block-failed")
                else:
                    self.frame_blocked = True
                    actions.append("frame-block")

        if self._previous is None:
            self._reset_baseline()
        else:
            current, policy = self._snapshot()
            if state is State.PAID:
                readings = delta(
                    self._previous, current,
                    self.config.rate_bytes_per_msat, "both",
                    policy_previous={self.session.npub: self._previous_policy},
                    policy_current={self.session.npub: policy},
                )
                reading = next((r for r in readings
                                if r.npub == self.session.npub), None)
                if reading is not None and reading.billable_bytes > 0:
                    billable = reading.billable_bytes
                    charged = self.session.charge(billable, now)
                    if self.session.state is State.GRACE and not self.paused:
                        result = self.gate.pause(self.session.npub)
                        self.paused = True
                        actions.append(f"pause:{result.mode}")
            # Frozen: advance the baseline without charging. A paused peer's
            # bytes (and anything sent between ticks) are never billed later.
            self._previous = current
            self._previous_policy = policy

        return ControllerResult(
            state=self.session.state.value,
            actions=actions,
            billable_bytes=billable,
            charged_msat=charged,
            paused=self.paused,
            evicted=self.evicted,
            frame_blocked=self.frame_blocked,
        )

    # -- events ----------------------------------------------------------

    def on_payment(self, amount_msat) -> ControllerResult:
        """Credit a verified payment and reopen forwarding if it was paused."""
        if self.evicted or self.session.state is State.EVICTED:
            raise ControllerError(
                "session is evicted; re-admit the peer and start a new session")
        self.session.pay(Decimal(amount_msat))
        actions: List[str] = []
        if self.paused:
            self.gate.resume(self.session.npub)
            self.paused = False
            actions.append("resume")
        self._reset_baseline()
        return ControllerResult(
            state=self.session.state.value,
            actions=actions,
            paused=self.paused,
            evicted=self.evicted,
            frame_blocked=self.frame_blocked,
        )

    def unblock_frame(self, mac: Optional[str] = None) -> bool:
        """Clear the L0 block on re-admission of the same device.

        This does not reset the session: re-admission is a new session, and
        the caller creates it. The method only removes the frame-gate block so
        the device can complete a new handshake.
        """
        if self.frame_gate is None:
            return False
        target = mac or self.mac
        self.frame_gate.unblock(target)
        if target == self.mac:
            self.frame_blocked = False
        return True


def run_until(gate: FipsGate, session: Session, stop, config=None,
              max_ticks: int = 10000) -> List[ControllerResult]:
    """Drive the controller until `stop()` is true or the tick budget ends."""
    controller = SellerController(gate, session, config)
    results: List[ControllerResult] = []
    period = (config or controller.config).tick_seconds
    for _ in range(max_ticks):
        results.append(controller.tick())
        if stop(controller, results[-1]):
            break
        time.sleep(period)
    return results
