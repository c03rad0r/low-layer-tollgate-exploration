"""Typed access to the `fipsctl` control-socket CLI (0.5.x)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .runner import LocalRunner, Result, RunnerError


class FipsctlError(RunnerError):
    pass


@dataclass
class Fipsctl:
    runner: Any = None

    def __post_init__(self) -> None:
        if self.runner is None:
            self.runner = LocalRunner()

    def _call(self, *argv: str) -> str:
        result: Result = self.runner.run(argv)
        if result.returncode != 0:
            raise FipsctlError(
                f"{' '.join(argv)} failed ({result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout

    def show(self, kind: str) -> Dict[str, Any]:
        try:
            return json.loads(self._call("fipsctl", "show", kind))
        except json.JSONDecodeError as exc:
            raise FipsctlError(f"fipsctl show {kind}: invalid JSON: {exc}") from exc

    def status(self) -> Dict[str, Any]:
        return self.show("status")

    def links(self) -> List[Dict[str, Any]]:
        return self.show("links").get("links", [])

    def peers(self) -> List[Dict[str, Any]]:
        return self.show("peers").get("peers", [])

    def transports(self) -> List[Dict[str, Any]]:
        return self.show("transports").get("transports", [])

    def routing(self) -> Dict[str, Any]:
        return self.show("routing")

    def policy_blocked(self) -> Dict[str, int]:
        forwarding = self.routing().get("forwarding", {})
        return {
            "packets": int(forwarding.get("drop_policy_blocked_packets", 0) or 0),
            "bytes": int(forwarding.get("drop_policy_blocked_bytes", 0) or 0),
        }

    def policy_blocked_for(self, npub: str) -> Dict[str, Any]:
        """Cumulative policy-dropped transit for one peer.

        `drop_policy_blocked_*` is node-wide; `policy_blocked_by_peer` carries
        the attribution. A peer with no entry has had nothing dropped.
        """
        forwarding = self.routing().get("forwarding", {}) or {}
        node_addr = None
        for peer in self.peers():
            if peer.get("npub") == npub:
                node_addr = peer.get("node_addr")
                break
        for row in forwarding.get("policy_blocked_by_peer", []) or []:
            if node_addr is not None and row.get("peer") == node_addr:
                return {
                    "peer": node_addr,
                    "packets": int(row.get("packets", 0) or 0),
                    "bytes": int(row.get("bytes", 0) or 0),
                }
        return {"peer": node_addr, "packets": 0, "bytes": 0}

    def acl(self) -> Dict[str, Any]:
        try:
            return json.loads(self._call("fipsctl", "acl", "show"))
        except json.JSONDecodeError as exc:
            raise FipsctlError(f"fipsctl acl show: invalid JSON: {exc}") from exc

    def disconnect(self, peer: str) -> str:
        return self._call("fipsctl", "disconnect", peer)

    def node_npub(self) -> Optional[str]:
        return self.status().get("npub")
