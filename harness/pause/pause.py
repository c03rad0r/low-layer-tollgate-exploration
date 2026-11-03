#!/usr/bin/env python3
"""Exp PAUSE: block one peer's transit while keeping its link.

Chain A -- B -- C. A and C dial B. A pings C through B. The patched B exposes
`set_forwarding` on its control socket:

  block A -> A's transit to C is dropped, A's link to B and A->B local traffic
             stay up
  allow A -> transit resumes

This is patch (b), the pause enabler: the link and Noise session survive, so
the payment path to the seller does not die with the forwarding role.
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

A, B, C = "lt-pause-a", "lt-pause-b", "lt-pause-c"


def control(npub: str, allow: bool) -> dict:
    result = exp_c.docker_exec(
        B, ["python3", "/pause/control.py", npub, "allow" if allow else "block"])
    text = result.stdout.strip()
    if result.returncode != 0:
        raise RuntimeError(f"control failed: {result.stderr.strip()}")
    return json.loads(text)


def main() -> int:
    a = Fipsctl(DockerRunner(A))
    b = Fipsctl(DockerRunner(B))
    c = Fipsctl(DockerRunner(C))
    clients = {"a": a, "b": b, "c": c}

    for name, client in clients.items():
        if exp_c.wait_for(lambda cl=client: exp_c.running(cl), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")
    a_status, b_status, c_status = a.status(), b.status(), c.status()
    a_npub, b_npub, c_npub = (s["npub"] for s in (a_status, b_status, c_status))
    b_addr = b_status["ipv6_addr"]
    c_addr = c_status["ipv6_addr"]
    print(f"a={a_npub} b={b_npub} c={c_npub} c_addr={c_addr}")

    # Both chain links up.
    link_ab, _ = exp_c.wait_for(
        lambda: exp_c.peer_for(a, b_npub) and exp_c.peer_for(b, a_npub), 20)
    link_bc, _ = exp_c.wait_for(
        lambda: exp_c.peer_for(c, b_npub) and exp_c.peer_for(b, c_npub), 20)
    if link_ab is None or link_bc is None:
        raise RuntimeError("chain links did not form")
    print(f"chain up: a-b={link_ab*1000:.0f} ms b-c={link_bc*1000:.0f} ms")

    # Raw ICMP does not trigger mesh discovery here; the probe does. Open and
    # tear down a diagnostic session to populate A's identity cache and route.
    exp_c.docker_exec(A, ["fipsctl", "probe", c_npub], timeout=40)

    # Wait for A -> C to route through B.
    start = time.monotonic()
    baseline_ac = {}
    while time.monotonic() - start < 40:
        baseline_ac = exp_c.ping6(A, c_addr, count=3)
        if baseline_ac["ok"]:
            break
        time.sleep(1.0)
    if not baseline_ac.get("ok"):
        print("FATAL: A cannot reach C through B", file=sys.stderr)
        print(baseline_ac, file=sys.stderr)
        return 2
    baseline_ab = exp_c.ping6(A, b_addr, count=3)
    print(f"baseline: a->c={baseline_ac['ok']} a->b={baseline_ab['ok']}")

    block = control(a_npub, allow=False)
    time.sleep(0.5)
    link_ab_after = exp_c.peer_for(b, a_npub) is not None
    ac_blocked = exp_c.ping6(A, c_addr, count=3)
    ab_still = exp_c.ping6(A, b_addr, count=3)
    print(f"block response: {json.dumps(block)}")
    print(f"blocked: a->c={ac_blocked['ok']} a->b={ab_still['ok']} "
          f"link_a_b={link_ab_after}")

    allow = control(a_npub, allow=True)
    time.sleep(0.5)
    ac_after = exp_c.ping6(A, c_addr, count=3)
    ab_after = exp_c.ping6(A, b_addr, count=3)
    print(f"allow response: {json.dumps(allow)}")
    print(f"allowed: a->c={ac_after['ok']} a->b={ab_after['ok']}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": b_status.get("version"),
        "nodes": {"a": a_npub, "b": b_npub, "c": c_npub},
        "chain": {"a_b_ms": round(link_ab * 1000),
                  "b_c_ms": round(link_bc * 1000)},
        "baseline": {"a_to_c": baseline_ac["ok"],
                     "a_to_b": baseline_ab["ok"]},
        "block": {
            "response": block,
            "a_to_c": ac_blocked["ok"],
            "a_to_b": ab_still["ok"],
            "link_a_b_preserved": link_ab_after,
        },
        "allow": {
            "response": allow,
            "a_to_c": ac_after["ok"],
            "a_to_b": ab_after["ok"],
        },
    }
    print()
    print(json.dumps(summary, indent=2))
    ok = (not ac_blocked["ok"] and ab_still["ok"] and link_ab_after
          and ac_after["ok"] and ab_after["ok"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
