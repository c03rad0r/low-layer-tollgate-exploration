#!/usr/bin/env python3
"""Exp MULTIPEER: block one client's transit, leave another untouched.

Star topology, all on one bridge:

    A (root) --- B (seller/transit) --- C
                     |
                     D

A, C and D dial B. B is the parent of C and D, and a child of A. A->D and
C->D both transit B. The patched B exposes `set_forwarding`:

  block A -> A->D is dropped at B; C->D keeps working; A->B local works;
             the A-B link survives; policy drops are filed under A only
  allow A -> A->D resumes

This is the multi-peer version of PB: the earlier run had one client, so it
could not show that the per-peer block is isolated.
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

A, B, C, D = "lt-mp-a", "lt-mp-b", "lt-mp-c", "lt-mp-d"
CONTAINERS = {"a": A, "b": B, "c": C, "d": D}
CYCLES = 3


def control(npub: str, allow: bool) -> dict:
    result = exp_c.docker_exec(
        B, ["python3", "/pause/control.py", npub, "allow" if allow else "block"])
    text = result.stdout.strip()
    if result.returncode != 0:
        raise RuntimeError(f"control failed: {result.stderr.strip()}")
    return json.loads(text)


def parent_info(fips: Fipsctl, name_of: dict) -> dict:
    peers = fips.peers()
    parent = next((p for p in peers if p.get("is_parent")), None)
    child = next((p for p in peers if p.get("is_child")), None)
    return {
        "is_root": parent is None,
        "parent": name_of.get(parent.get("node_addr")) if parent else None,
        "child": name_of.get(child.get("node_addr")) if child else None,
        "peers": len(peers),
        "tree_depth": (parent or {}).get("tree_depth"),
        "effective_depth": (parent or {}).get("effective_depth"),
    }


def attribution(fips: Fipsctl, name_of: dict) -> list:
    routing = fips.routing()
    rows = (routing.get("forwarding", {}) or {}).get(
        "policy_blocked_by_peer", []) or []
    out = []
    for row in rows:
        npub = name_of.get(row.get("peer"), row.get("peer"))
        out.append({
            "node": npub,
            "peer": row.get("peer"),
            "packets": row.get("packets"),
            "bytes": row.get("bytes"),
        })
    return out


def main() -> int:
    clients = {name: Fipsctl(DockerRunner(container))
               for name, container in CONTAINERS.items()}

    for name, client in clients.items():
        if exp_c.wait_for(lambda cl=client: exp_c.running(cl), 25)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")

    status = {name: client.status() for name, client in clients.items()}
    npubs = {name: st["npub"] for name, st in status.items()}
    name_of = {st["node_addr"]: name for name, st in status.items()}
    # FIPS records the peer's node_addr, not its npub, in routing rows.
    print("npubs: " + json.dumps(npubs))
    print("addrs: " + json.dumps({name: st["node_addr"]
                                 for name, st in status.items()}))

    # Every client link up.
    for client_name, peer_name in (("a", "b"), ("c", "b"), ("d", "b")):
        waited, _ = exp_c.wait_for(
            lambda cn=client_name, pn=peer_name: (
                exp_c.peer_for(clients[cn], npubs[pn])
                and exp_c.peer_for(clients[pn], npubs[cn])), 25)
        if waited is None:
            raise RuntimeError(f"link {client_name}-{peer_name} did not form")
        print(f"link {client_name}-{peer_name} up in {waited*1000:.0f} ms")

    # Raw ICMP does not trigger mesh discovery; probe the npub first.
    for node in (A, C):
        exp_c.docker_exec(node, ["fipsctl", "probe", npubs["d"]], timeout=40)

    d_addr = status["d"]["ipv6_addr"]
    b_addr = status["b"]["ipv6_addr"]

    def wait_reach(container: str, addr: str, label: str) -> dict:
        start = time.monotonic()
        last = {}
        while time.monotonic() - start < 40:
            last = exp_c.ping6(container, addr, count=3)
            if last["ok"]:
                return last
            time.sleep(1.0)
        raise RuntimeError(f"{label} did not come up: {last}")

    baseline_ad = wait_reach(A, d_addr, "a->d")
    baseline_cd = wait_reach(C, d_addr, "c->d")
    baseline_ab = exp_c.ping6(A, b_addr, count=3)
    baseline_cb = exp_c.ping6(C, b_addr, count=3)
    print(f"baseline: a->d={baseline_ad['ok']} c->d={baseline_cd['ok']} "
          f"a->b={baseline_ab['ok']} c->b={baseline_cb['ok']}")

    # Read the tree only once positions have settled; right after the links
    # form, `has_tree_position` can still be false and `is_parent` is absent.
    waited, _ = exp_c.wait_for(
        lambda: all(p.get("has_tree_position") for p in clients["b"].peers()),
        20)
    if waited is None:
        raise RuntimeError("tree positions did not settle")
    topology = {name: parent_info(client, name_of)
                for name, client in clients.items()}
    print("topology: " + json.dumps(topology))
    if topology["b"]["is_root"] is not True:
        print("FATAL: B is not the root; transit premise changed", file=sys.stderr)
        print(json.dumps(topology, indent=2), file=sys.stderr)
        return 2

    cycles = []
    for index in range(CYCLES):
        before = attribution(clients["b"], name_of)
        block = control(npubs["a"], allow=False)
        time.sleep(0.5)
        link_ab = exp_c.peer_for(clients["b"], npubs["a"]) is not None
        blocked_ad = exp_c.ping6(A, d_addr, count=3)
        blocked_cd = exp_c.ping6(C, d_addr, count=3)
        blocked_ab = exp_c.ping6(A, b_addr, count=3)
        blocked_cb = exp_c.ping6(C, b_addr, count=3)
        after = attribution(clients["b"], name_of)
        rows_a = [r for r in after if r["node"] == "a"]
        rows_c = [r for r in after if r["node"] == "c"]

        allow = control(npubs["a"], allow=True)
        time.sleep(0.5)
        allowed_ad = exp_c.ping6(A, d_addr, count=3)
        allowed_cd = exp_c.ping6(C, d_addr, count=3)

        cycle = {
            "cycle": index + 1,
            "block_response": block,
            "allow_response": allow,
            "blocked": {
                "a_to_d_ok": blocked_ad["ok"],
                "a_to_d_loss_pct": blocked_ad["loss_pct"],
                "c_to_d_ok": blocked_cd["ok"],
                "c_to_d_loss_pct": blocked_cd["loss_pct"],
                "a_to_b_ok": blocked_ab["ok"],
                "c_to_b_ok": blocked_cb["ok"],
                "link_a_b": link_ab,
            },
            "allowed": {
                "a_to_d_ok": allowed_ad["ok"],
                "c_to_d_ok": allowed_cd["ok"],
            },
            "attribution_before": before,
            "attribution_after": after,
            "attributed_to_a": rows_a,
            "attributed_to_c": rows_c,
        }
        cycles.append(cycle)
        print(f"cycle {index + 1}: " + json.dumps(cycle))

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "topology": topology,
        "npubs": npubs,
        "baseline": {
            "a_to_d": baseline_ad["ok"], "c_to_d": baseline_cd["ok"],
            "a_to_b": baseline_ab["ok"], "c_to_b": baseline_cb["ok"],
        },
        "cycles": cycles,
    }
    print(json.dumps(summary, indent=2))

    # Every cycle: A blocked, C untouched, A's local path and link intact,
    # drops filed under A only, and allow restores A.
    for cycle in cycles:
        b = cycle["blocked"]
        rows_a = cycle["attributed_to_a"]
        rows_c = cycle["attributed_to_c"]
        if b["a_to_d_ok"] or not b["c_to_d_ok"] or not b["a_to_b_ok"]:
            return 1
        if not b["c_to_b_ok"] or not b["link_a_b"]:
            return 1
        if not cycle["allowed"]["a_to_d_ok"] or not cycle["allowed"]["c_to_d_ok"]:
            return 1
        if not rows_a or (rows_a[0]["bytes"] or 0) <= 0:
            return 1
        if rows_c and (rows_c[0]["bytes"] or 0) > 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
