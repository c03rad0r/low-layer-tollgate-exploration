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

    def disconnect(self, peer: str) -> str:
        return self._call("fipsctl", "disconnect", peer)

    def node_npub(self) -> Optional[str]:
        return self.status().get("npub")
