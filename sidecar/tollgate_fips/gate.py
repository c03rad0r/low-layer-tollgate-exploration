"""The gate: admit, deny, meter, pause, evict.

`pause` is the verb FIPS cannot implement today. Strict mode raises rather than
pretending. Crude mode disconnects and says so, which is the Phase 1 demo.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

from .control import ControlError
from .fipsctl import Fipsctl
from .meter import LinkCounters, MeterReading, delta, snapshot
from .runner import RunnerError


class GateError(RuntimeError):
    pass


class AclError(GateError):
    pass


class PauseUnsupported(GateError):
    """FIPS has no per-peer forwarding role; a real pause is not possible."""


class PeerNotFound(GateError):
    pass


@dataclass(frozen=True)
class PauseResult:
    paused: bool
    mode: str
    warning: Optional[str] = None
    acl_wait_ms: Optional[int] = None


@dataclass(frozen=True)
class EvictResult:
    mode: str
    acl_wait_ms: Optional[int] = None
    disconnect_output: str = ""


class FileAclStore:
    """The FIPS peer ACL, as two newline-delimited files.

    This is the only runtime admission lever in FIPS 0.5.x. The daemon reloads
    on its next 1 s tick (Exp B: 756-984 ms).
    """

    def __init__(self, allow_path: str, deny_path: str):
        self.allow_path = allow_path
        self.deny_path = deny_path

    def _read(self, path: str) -> list:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return [line.strip() for line in handle if line.strip()]
        except FileNotFoundError:
            return []

    def _append(self, path: str, npub: str) -> bool:
        if npub in self._read(path):
            return False
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(npub + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise AclError(f"cannot append to {path}: {exc}") from exc
        return True

    def _remove(self, path: str, npub: str) -> bool:
        """Atomically remove one line. Single-writer assumption.

        The daemon reloads on mtime, so replacing the inode is fine; the mode is
        preserved so the file stays readable by the service user.
        """
        lines = self._read(path)
        if npub not in lines:
            return False
        kept = [line for line in lines if line != npub]
        tmp = path + ".tollgate-tmp"
        try:
            mode = os.stat(path).st_mode & 0o777
            with open(tmp, "w", encoding="utf-8") as handle:
                if kept:
                    handle.write("\n".join(kept) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise AclError(f"cannot rewrite {path}: {exc}") from exc
        return True

    def allow(self, npub: str) -> bool:
        removed = self._remove(self.deny_path, npub)
        added = self._append(self.allow_path, npub)
        return removed or added

    def deny(self, npub: str) -> bool:
        removed = self._remove(self.allow_path, npub)
        added = self._append(self.deny_path, npub)
        return removed or added

    def allowed(self, npub: str) -> bool:
        return npub in self._read(self.allow_path)

    def denied(self, npub: str) -> bool:
        return npub in self._read(self.deny_path)

    def entries(self):
        return self._read(self.allow_path), self._read(self.deny_path)


class FipsGate:
    def __init__(
        self,
        fipsctl: Optional[Fipsctl] = None,
        acl: Optional[FileAclStore] = None,
        allow_disconnect: bool = False,
        control=None,
    ):
        self.fipsctl = fipsctl or Fipsctl()
        self.acl = acl
        self.allow_disconnect = allow_disconnect
        self.control = control

    # -- admission -------------------------------------------------------

    def admit(self, npub: str) -> bool:
        if self.acl is None:
            raise AclError("no ACL store configured; cannot admit")
        return self.acl.allow(npub)

    def deny(self, npub: str) -> bool:
        if self.acl is None:
            raise AclError("no ACL store configured; cannot deny")
        return self.acl.deny(npub)

    # -- metering --------------------------------------------------------

    def counters(self) -> Dict[Tuple[str, int], LinkCounters]:
        return snapshot(self.fipsctl.peers(), self.fipsctl.links())

    def policy_blocked(self) -> dict:
        """Node-wide policy-dropped counters."""
        return self.fipsctl.policy_blocked()

    def policy_blocked_for(self, npub: str) -> dict:
        """Cumulative policy-dropped bytes attributed to one peer.

        Pass this (as a before/after pair) to `meter.delta` so a paused peer's
        refused transit is never billed.
        """
        return self.fipsctl.policy_blocked_for(npub)

    def meter(
        self,
        npub: str,
        rate_bytes_per_msat: Decimal,
        direction: str = "both",
        previous: Optional[Dict[Tuple[str, int], LinkCounters]] = None,
    ) -> MeterReading:
        current = self.counters()
        if not any(key[0] == npub for key in current):
            raise PeerNotFound(f"{npub} has no link on this node")
        readings = delta(previous or {}, current, rate_bytes_per_msat, direction)
        for reading in readings:
            if reading.npub == npub:
                return reading
        raise PeerNotFound(f"{npub} has no counters")

    # -- pause / evict ---------------------------------------------------

    def pause(self, npub: str) -> PauseResult:
        # Patched FIPS: block transit, keep the link and local delivery.
        if self.control is not None:
            try:
                self.control.set_forwarding(npub, allow=False)
                return PauseResult(
                    paused=True,
                    mode="transit-blocked",
                    warning=(
                        "transit blocked; the link, Noise session and local "
                        "delivery are preserved"
                    ),
                )
            except (ControlError, OSError) as exc:
                if not self.allow_disconnect:
                    raise PauseUnsupported(
                        "set_forwarding failed and allow_disconnect is off: "
                        f"{exc}"
                    ) from exc

        if not self.allow_disconnect:
            raise PauseUnsupported(
                "FIPS has no per-peer forwarding role. The link can only be "
                "kept (and forwarding continued) or disconnected. Use "
                "allow_disconnect=True for the crude Phase 1 fallback."
            )
        result = self.evict(npub, durable=True)
        return PauseResult(
            paused=False,
            mode=result.mode,
            warning=(
                "pause degraded to eviction: the link and the payment lane are "
                "gone, and the npub is denied so auto_connect cannot bring the "
                "link back without a new admission. This is the evidence for "
                "FIPS patch (b) and P4."
            ),
            acl_wait_ms=result.acl_wait_ms,
        )

    def resume(self, npub: str) -> Any:
        """Clear a transit block. Requires the patched control command."""
        if self.control is None:
            raise GateError("no control client; cannot resume forwarding")
        try:
            return self.control.set_forwarding(npub, allow=True)
        except (ControlError, OSError) as exc:
            raise GateError(f"resume failed: {exc}") from exc

    def evict(self, npub: str, durable: bool = True) -> EvictResult:
        """Close the link, durably by default.

        A bare `disconnect` is not eviction: with auto_connect the peer dials
        again and is re-admitted without a new payment (Exp C: ~6.8 s, new
        link_id). Durable eviction therefore denies the npub, waits for the ACL
        to take effect, and only then disconnects.
        """
        acl_wait_ms = None
        if durable:
            if self.acl is None:
                raise GateError(
                    "durable eviction requires an ACL store; a bare disconnect "
                    "is re-established by auto_connect"
                )
            self.acl.deny(npub)
            acl_wait_ms = self._wait_denied(npub)
        output = self.fipsctl.disconnect(npub)
        return EvictResult(
            mode="deny+disconnect" if durable else "disconnect",
            acl_wait_ms=acl_wait_ms,
            disconnect_output=output,
        )

    def _wait_denied(self, npub: str, timeout: float = 5.0) -> int:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            try:
                state = self.fipsctl.acl()
            except RunnerError:
                time.sleep(0.05)
                continue
            allow = state.get("allow_entries") or []
            denied = state.get("deny_entries") or []
            if npub not in allow and (state.get("deny_all") or npub in denied):
                return int((time.monotonic() - started) * 1000)
            time.sleep(0.05)
        raise GateError(f"ACL deny for {npub} not effective within {timeout}s")
