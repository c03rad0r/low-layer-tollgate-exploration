#!/usr/bin/env python3
"""Exp ETH: the gate over the Ethernet transport.

Two FIPS nodes on a Docker L2 bridge. Both enable the Ethernet transport with
neighbour beacons; there are no static peer entries. The experiment measures:

1. beacon discovery time (no address config);
2. metering at the same FMP frame boundary;
3. runtime deny -> a disconnected peer cannot re-admit;
4. runtime allow -> beacon re-discovery and handshake, measured.
"""

from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))

import exp_c  # noqa: E402
from tollgate_fips.fipsctl import Fipsctl  # noqa: E402
from tollgate_fips.meter import delta, snapshot  # noqa: E402
from tollgate_fips.runner import DockerRunner, RunnerError  # noqa: E402

A = "lt-eth-a"
B = "lt-eth-b"


def admission(action: str, npub: str) -> dict:
    result = exp_c.docker_exec(B, ["fipsctl", "admission", npub, action])
    if result.returncode != 0:
        raise RuntimeError(f"admission {action} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def wait_link(a: Fipsctl, b: Fipsctl, a_npub: str, b_npub: str, timeout: float):
    started = time.monotonic()
    elapsed, pair = exp_c.wait_link(a, b, a_npub, b_npub, timeout)
    return None if pair is None else (time.monotonic() - started) * 1000, pair


def main() -> int:
    a = Fipsctl(DockerRunner(A))
    b = Fipsctl(DockerRunner(B))
    for name, client in (("a", a), ("b", b)):
        if exp_c.wait_for(lambda c=client: exp_c.running(c), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")

    a_status, b_status = a.status(), b.status()
    a_npub, b_npub = a_status["npub"], b_status["npub"]
    b_addr = b_status["ipv6_addr"]

    eth = next((t for t in b.transports() if t.get("type") == "ethernet"), None)

    # 1. Beacon discovery: no peer entries and no addresses configured.
    discovery_ms, pair = wait_link(a, b, a_npub, b_npub, 45)
    if pair is None:
        print("FATAL: beacon discovery did not form a link", file=sys.stderr)
        print(json.dumps({"transports": b.transports(),
                          "peers": b.peers()}, indent=2), file=sys.stderr)
        return 2
    link_id = pair[0].get("link_id")
    print(f"discovered in {discovery_ms:.0f} ms, link_id={link_id}")

    # 2. Metering at the FMP frame boundary.
    before = snapshot(b.peers(), b.links())
    ping = exp_c.ping6(A, b_addr, count=10, size=1200)
    time.sleep(0.05)
    after = snapshot(b.peers(), b.links())
    reading = next((r for r in delta(before, after, Decimal("1"), "both")
                    if r.npub == a_npub), None)
    print(f"ping ok={ping['ok']} billable={reading.billable_bytes if reading else 0}")

    # 3. Runtime deny + disconnect: no re-admission.
    admission("deny", a_npub)
    try:
        b.disconnect(a_npub)
    except RunnerError:
        pass
    exp_c.wait_for(lambda: exp_c.peer_for(b, a_npub) is None, 5)
    exp_c.wait_for(lambda: exp_c.peer_for(a, b_npub) is None, 5)
    deny_held = True
    started = time.monotonic()
    while time.monotonic() - started < 4.0:
        if exp_c.peer_for(b, a_npub) or exp_c.peer_for(a, b_npub):
            deny_held = False
            break
        time.sleep(0.1)
    print(f"deny held for 4 s: {deny_held}")

    # 4. Runtime allow: beacon re-discovery + handshake.
    admission("allow", a_npub)
    readmit_ms, pair2 = wait_link(a, b, a_npub, b_npub, 40)
    if pair2 is None:
        raise RuntimeError("peer did not re-admit after allow")
    after_ping = exp_c.ping6(A, b_addr, count=3)
    print(f"re-admitted in {readmit_ms:.0f} ms, ping={after_ping['ok']}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": b_status.get("version"),
        "transport": "ethernet",
        "nodes": {"a": a_npub, "b": b_npub},
        "ethernet_transport": eth,
        "discovery_ms": round(discovery_ms),
        "link_id": link_id,
        "ping_ok": ping["ok"],
        "billable_bytes": reading.billable_bytes if reading else 0,
        "deny_held": deny_held,
        "readmit_ms": round(readmit_ms),
        "readmit_link_id": pair2[0].get("link_id"),
        "ping_after_readmit": after_ping["ok"],
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0 if (ping["ok"] and deny_held and after_ping["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
