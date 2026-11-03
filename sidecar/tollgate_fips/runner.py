"""Run `fipsctl` locally or over SSH.

The sidecar normally runs on the seller node and uses `LocalRunner`. `SSHRunner`
exists for read-only inspection of a fleet node during development; it is not
used for ACL writes.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence


class RunnerError(RuntimeError):
    """A command failed or produced no output."""


@dataclass
class Result:
    argv: Sequence[str]
    returncode: int
    stdout: str
    stderr: str


class LocalRunner:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def run(self, argv: Sequence[str], stdin: Optional[str] = None) -> Result:
        proc = subprocess.run(
            list(argv),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return Result(list(argv), proc.returncode, proc.stdout, proc.stderr)


class SSHRunner:
    """Run a command on `host` through ssh with BatchMode.

    Read-only by convention. Do not use this for ACL writes: the sidecar should
    run on the node that owns the control socket.
    """

    def __init__(self, host: str, timeout: float = 15.0, ssh: str = "ssh"):
        self.host = host
        self.timeout = timeout
        self.ssh = ssh

    def run(self, argv: Sequence[str], stdin: Optional[str] = None) -> Result:
        remote = shlex.join(list(argv))
        proc = subprocess.run(
            [self.ssh, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             self.host, remote],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return Result(list(argv), proc.returncode, proc.stdout, proc.stderr)
