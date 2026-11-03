"""The gate: admit, deny, meter, pause, evict.

`pause` is the verb FIPS cannot implement today. Strict mode raises rather than
pretending. Crude mode disconnects and says so, which is the Phase 1 demo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

from .fipsctl import Fipsctl
from .meter import LinkCounters, MeterReading, delta, snapshot


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


class FipsGate:
    def __init__(
        self,
        fipsctl: Optional[Fipsctl] = None,
        acl: Optional[FileAclStore] = None,
        allow_disconnect: bool = False,
    ):
        self.fipsctl = fipsctl or Fipsctl()
        self.acl = acl
        self.allow_disconnect = allow_disconnect

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
        if not self.allow_disconnect:
            raise PauseUnsupported(
                "FIPS has no per-peer forwarding role. The link can only be "
                "kept (and forwarding continued) or disconnected. Use "
                "allow_disconnect=True for the crude Phase 1 fallback."
            )
        self.evict(npub)
        return PauseResult(
            paused=False,
            mode="disconnect",
            warning=(
                "pause degraded to disconnect: the link and the payment lane "
                "are gone. This is the evidence for FIPS patch (b) and P4."
            ),
        )

    def evict(self, npub: str) -> str:
        return self.fipsctl.disconnect(npub)
