#!/usr/bin/env python3
"""Exp A2: runtime admission (patch a) vs the ACL-file tick.

Two-node pair from `harness/exp-c`. Measures four things on the seller:

1. file deny -> `acl show` effective (the 1 s tick, Exp B);
2. runtime deny -> a fresh handshake is refused without waiting for the file;
3. runtime allow -> time from an explicit connect to a usable link;
4. runtime clear -> falls back to the file ACL.

Admission only gates new handshakes; it does not drop an established link, so
each measurement disconnects first.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))

import exp_c  # noqa: E402
from tollgate_fips.fipsctl import Fipsctl  # noqa: E402
from tollgate_fips.runner import DockerRunner, RunnerError  # noqa: E402

SELLER = "lt-exp-c-seller"
BUYER = "lt-exp-c-buyer"


def admission(action: str, npub: str) -> dict:
    started = time.monotonic()
    result = exp_c.docker_exec(SELLER, ["fipsctl", "admission", npub, action])
    ms = (time.monotonic() - started) * 1000
    if result.returncode != 0:
        raise RuntimeError(f"admission {action} failed: {result.stderr.strip()}")
    return {"action": action, "cmd_ms": round(ms),
            "output": result.stdout.strip()}


def down(client: Fipsctl, npub: str) -> None:
    try:
        client.disconnect(npub)
    except RunnerError:
        pass


def force_connect(buyer: Fipsctl, seller_npub: str, seller_addr: str) -> None:
    down(buyer, seller_npub)
    time.sleep(0.1)
    exp_c.docker_exec(BUYER, ["fipsctl", "connect", seller_npub,
                              f"{seller_addr}:2121", "udp"])


def wait_link(seller: Fipsctl, buyer: Fipsctl, seller_npub: str,
              buyer_npub: str, timeout: float):
    started = time.monotonic()
    elapsed, pair = exp_c.wait_link(seller, buyer, seller_npub, buyer_npub,
                                     timeout)
    return None if pair is None else (time.monotonic() - started) * 1000, pair


def no_link_for(seller: Fipsctl, buyer: Fipsctl, seller_npub: str,
                buyer_npub: str, seconds: float) -> bool:
    """True if no link ever appears during the window."""
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if (exp_c.peer_for(seller, buyer_npub)
                and exp_c.peer_for(buyer, seller_npub)):
            return False
        time.sleep(0.05)
    return True


def main() -> int:
    seller = Fipsctl(DockerRunner(SELLER))
    buyer = Fipsctl(DockerRunner(BUYER))
    for name, client in (("seller", seller), ("buyer", buyer)):
        if exp_c.wait_for(lambda c=client: exp_c.running(c), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")

    seller_status = seller.status()
    seller_npub = seller_status["npub"]
    buyer_npub = buyer.status()["npub"]
    seller_addr = seller_status["ipv6_addr"]

    # Start from a file allow.
    file_allow_ms = exp_c.measure_acl_write(SELLER, buyer_npub)[0] * 1000
    latency, pair = wait_link(seller, buyer, seller_npub, buyer_npub, 10)
    if pair is None:
        force_connect(buyer, seller_npub, seller_addr)
        latency, pair = wait_link(seller, buyer, seller_npub, buyer_npub, 10)
    if pair is None:
        raise RuntimeError("baseline link did not form")

    # 1. File deny: measure the tick the ACL waits for.
    file_deny_ms = exp_c.measure_acl_write(SELLER, None)[0] * 1000

    # The existing link stays up; admission gates the next handshake only.
    down(seller, buyer_npub)
    exp_c.wait_for(lambda: exp_c.peer_for(seller, buyer_npub) is None, 5)

    # 2. Runtime deny must refuse a fresh handshake immediately.
    deny = admission("deny", buyer_npub)
    force_connect(buyer, seller_npub, seller_addr)
    runtime_deny_held = no_link_for(seller, buyer, seller_npub, buyer_npub, 2.0)

    # 3. Runtime allow overrides the file deny; measure link formation only.
    allow = admission("allow", buyer_npub)
    force_connect(buyer, seller_npub, seller_addr)
    runtime_readmit_ms, pair = wait_link(seller, buyer, seller_npub,
                                         buyer_npub, 10)
    if pair is None:
        raise RuntimeError("runtime allow did not re-admit")

    # 4. Clear falls back to the file deny.
    down(seller, buyer_npub)
    exp_c.wait_for(lambda: exp_c.peer_for(seller, buyer_npub) is None, 5)
    clear = admission("clear", buyer_npub)
    force_connect(buyer, seller_npub, seller_addr)
    clear_held = no_link_for(seller, buyer, seller_npub, buyer_npub, 2.0)

    # 5. File allow again for the comparison path. The file path pays the ACL
    # tick before the handshake, so the clock starts before the write.
    file_started = time.monotonic()
    file_reallow_ms = exp_c.measure_acl_write(SELLER, buyer_npub)[0] * 1000
    force_connect(buyer, seller_npub, seller_addr)
    _, pair = wait_link(seller, buyer, seller_npub, buyer_npub, 10)
    file_readmit_ms = (time.monotonic() - file_started) * 1000
    if pair is None:
        raise RuntimeError("file allow did not re-admit")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": seller_status.get("version"),
        "seller_npub": seller_npub,
        "buyer_npub": buyer_npub,
        "baseline_link_ms": round(latency),
        "file": {
            "allow_ms": round(file_allow_ms),
            "deny_ms": round(file_deny_ms),
            "reallow_ms": round(file_reallow_ms),
        },
        "runtime": {
            "deny_cmd_ms": deny["cmd_ms"],
            "deny_held": runtime_deny_held,
            "allow_cmd_ms": allow["cmd_ms"],
            "readmit_ms": round(runtime_readmit_ms),
            "clear_cmd_ms": clear["cmd_ms"],
            "clear_fell_back_to_file": clear_held,
        },
        "file_readmit_total_ms": round(file_readmit_ms),
        "saved_ms": round(file_readmit_ms - runtime_readmit_ms),
    }
    print()
    print(json.dumps(summary, indent=2))
    ok = (runtime_deny_held and clear_held
          and runtime_readmit_ms is not None and file_readmit_ms is not None)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
