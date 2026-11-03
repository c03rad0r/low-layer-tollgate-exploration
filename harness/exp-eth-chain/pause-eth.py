#!/usr/bin/env python3
"""Exp ETH-CHAIN: pause semantics over a dual-homed Ethernet chain.

    A --- (eth0) B (eth1) --- C

A and C are on separate Docker L2 bridges; B has one Ethernet transport on
each, so the only path A->C is through B. This is the PB test over Ethernet:
block A's transit at B and check A->C stops while A->B and the A-B link stay.
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
from tollgate_fips.runner import DockerRunner  # noqa: E402

A, B, C = "lt-ethc-a", "lt-ethc-b", "lt-ethc-c"


def forwarding(action: str, npub: str) -> dict:
    result = exp_c.docker_exec(B, ["fipsctl", "set-forwarding", npub, action])
    if result.returncode != 0:
        raise RuntimeError(
            f"set-forwarding {action} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def wait_link(a: Fipsctl, b: Fipsctl, a_npub: str, b_npub: str,
              timeout: float):
    started = time.monotonic()
    elapsed, pair = exp_c.wait_link(a, b, a_npub, b_npub, timeout)
    return None if pair is None else (time.monotonic() - started) * 1000, pair


def main() -> int:
    a = Fipsctl(DockerRunner(A))
    b = Fipsctl(DockerRunner(B))
    c = Fipsctl(DockerRunner(C))
    for name, client in (("a", a), ("b", b), ("c", c)):
        if exp_c.wait_for(lambda cl=client: exp_c.running(cl), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")

    a_status, b_status, c_status = a.status(), b.status(), c.status()
    a_npub, b_npub, c_npub = (s["npub"] for s in (a_status, b_status, c_status))
    b_addr = b_status["ipv6_addr"]
    c_addr = c_status["ipv6_addr"]

    ab_ms, pair_ab = wait_link(a, b, a_npub, b_npub, 45)
    if pair_ab is None:
        print("FATAL: A-B did not form", file=sys.stderr)
        print(json.dumps({"a": a.transports(), "b": b.transports()},
                         indent=2), file=sys.stderr)
        return 2
    bc_ms, pair_bc = wait_link(c, b, c_npub, b_npub, 45)
    if pair_bc is None:
        raise RuntimeError("B-C did not form")
    link_id_ab = pair_ab[0].get("link_id")
    print(f"chain up: a-b={ab_ms:.0f} ms b-c={bc_ms:.0f} ms")

    # Warm identity/coords; raw ICMP does not trigger discovery.
    exp_c.docker_exec(A, ["fipsctl", "probe", c_npub], timeout=40)

    started = time.monotonic()
    baseline = {}
    while time.monotonic() - started < 40:
        baseline = exp_c.ping6(A, c_addr, count=3)
        if baseline["ok"]:
            break
        time.sleep(1.0)
    if not baseline.get("ok"):
        print("FATAL: A cannot reach C through B", file=sys.stderr)
        print(json.dumps(baseline, indent=2), file=sys.stderr)
        return 2
    a_to_b = exp_c.ping6(A, b_addr, count=3)
    print(f"baseline: a->c={baseline['ok']} a->b={a_to_b['ok']}")

    link_id_pre_block = (exp_c.peer_for(b, a_npub) or {}).get("link_id")
    block = forwarding("block", a_npub)
    time.sleep(0.3)
    blocked = exp_c.ping6(A, c_addr, count=3)
    still_ab = exp_c.ping6(A, b_addr, count=3)
    link_now = exp_c.peer_for(b, a_npub)
    link_kept = (link_now is not None
                 and link_now.get("link_id") == link_id_pre_block)
    routing = b.routing()
    by_peer = (routing.get("forwarding", {}) or {}).get(
        "policy_blocked_by_peer", []) or []
    a_peer = next((row for row in b.peers()
                   if row.get("npub") == a_npub), {})
    a_row = next((row for row in by_peer
                  if row.get("peer") == a_peer.get("node_addr")), None)
    print(f"blocked: a->c={blocked['ok']} a->b={still_ab['ok']} "
          f"link_kept={link_kept} dropped={a_row}")

    allow = forwarding("allow", a_npub)
    time.sleep(0.3)
    allowed = exp_c.ping6(A, c_addr, count=3)
    print(f"allowed: a->c={allowed['ok']}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": b_status.get("version"),
        "transport": "ethernet",
        "nodes": {"a": a_npub, "b": b_npub, "c": c_npub},
        "chain": {"a_b_ms": round(ab_ms), "b_c_ms": round(bc_ms)},
        "baseline": {"a_to_c": baseline["ok"], "a_to_b": a_to_b["ok"]},
        "block": {
            "response": block,
            "a_to_c": blocked["ok"],
            "a_to_b": still_ab["ok"],
            "link_id_initial": link_id_ab,
            "link_id_pre_block": link_id_pre_block,
            "link_preserved": link_kept,
            "attributed": a_row,
        },
        "allow": {"response": allow, "a_to_c": allowed["ok"]},
        "b_transports": b.transports(),
    }
    print()
    print(json.dumps(summary, indent=2))
    ok = (baseline["ok"] and not blocked["ok"] and still_ab["ok"]
          and link_kept and allowed["ok"] and a_row and a_row["bytes"] > 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
