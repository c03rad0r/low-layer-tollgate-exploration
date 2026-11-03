"""Unix control-socket client for mutating FIPS commands.

The CLI (`fipsctl`) covers read queries and connect/disconnect, but not the local
patch's `set_forwarding` command. The sidecar uses this small client for the
pause hook. It is deliberately transport-local: the seller owns the socket.
"""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, Optional

DEFAULT_SOCKET = "/run/fips/control.sock"


class ControlError(RuntimeError):
    pass


class UnixControl:
    def __init__(self, socket_path: str = DEFAULT_SOCKET, timeout: float = 2.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def command(self, command: str, params: Optional[Dict[str, Any]] = None) -> Any:
        request = {"command": command}
        if params is not None:
            request["params"] = params
        payload = (json.dumps(request) + "\n").encode()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            sock.sendall(payload)
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk

        try:
            response = json.loads(data.decode())
        except json.JSONDecodeError as exc:
            raise ControlError(f"invalid control response: {data!r}") from exc
        if response.get("status") != "ok":
            raise ControlError(response.get("message") or "control command failed")
        return response.get("data")

    def set_forwarding(self, npub: str, allow: bool) -> Any:
        return self.command("set_forwarding", {"npub": npub, "allow": allow})
