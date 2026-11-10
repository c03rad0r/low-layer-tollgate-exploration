#!/usr/bin/env python3
"""E-BYPASS: can a blocked peer bypass a per-node transit block by re-parenting?

Topology:

    B (root, passive)
    | \
    |  C --- D
    | /
    A

A's parent is B; D's parent is C. A->D therefore goes A-B-C-D. Blocking A at B
stops it. A also has a direct link to C; after denying B on A and disconnecting
A-B, A re-parents to C and reaches D via A-C-D, bypassing B's block. Blocking A
at C as well stops it.
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

NODES = {"a": "lt-byp-a", "b": "lt-byp-b", "c": "lt-byp-c", "d": "lt-byp-d"}
CYCLES = 3


def control(container: str, npub: str, allow: bool) -> dict:
    result = exp_c.docker_exec(
        container, ["python3", "/pause/control.py", npub,
                    "allow" if allow else "block"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout.strip())


def parent_name(fips: Fipsctl, name_of: dict):
    for peer in fips.peers():
        if peer.get("is_parent"):
            return name_of.get(peer.get("node_addr") or peer.get("npub"))
    return None


def write_acl(container: str, allows: list[str]) -> None:
    allow = ("\n".join(allows) + "\n") if allows else ""
    code = (
        "import pathlib;"
        "pathlib.Path('/etc/fips/peers.allow').write_text(%r);"
        "pathlib.Path('/etc/fips/peers.deny').write_text('ALL\\n')"
    ) % allow
    exp_c.docker_exec(container, ["python3", "-c", code])


def main() -> int:
    clients = {n: Fipsctl(DockerRunner(c)) for n, c in NODES.items()}
    for n, cl in clients.items():
        if exp_c.wait_for(lambda c=cl: exp_c.running(c), 25)[0] is None:
            raise RuntimeError(f"{n} did not start")

    status = {n: cl.status() for n, cl in clients.items()}
    npub = {n: s["npub"] for n, s in status.items()}
    name_of = {}
    for n, s in status.items():
        name_of[s["node_addr"]] = n
        name_of[s["npub"]] = n
    print("npubs: " + json.dumps(npub))

    for x, y in (("a", "b"), ("a", "c"), ("b", "c"), ("c", "d")):
        waited, _ = exp_c.wait_for(
            lambda x=x, y=y: (exp_c.peer_for(clients[x], npub[y])
                              and exp_c.peer_for(clients[y], npub[x])), 30)
        if waited is None:
            raise RuntimeError(f"link {x}-{y} did not form")
        print(f"link {x}-{y} up in {waited*1000:.0f} ms")

    for node in ("a", "c"):
        exp_c.docker_exec(NODES[node], ["fipsctl", "probe", npub["d"]],
                          timeout=40)
    d_addr = status["d"]["ipv6_addr"]

    def wait_reach(container, addr, label):
        start = time.monotonic()
        last = {}
        while time.monotonic() - start < 40:
            last = exp_c.ping6(container, addr, count=3)
            if last["ok"]:
                return last
            time.sleep(1)
        raise RuntimeError(f"{label} unreachable: {last}")

    baseline_ad = wait_reach(NODES["a"], d_addr, "a->d")
    baseline_cd = wait_reach(NODES["c"], d_addr, "c->d")

    def topology():
        return {n: {"parent": parent_name(cl, name_of),
                    "peers": len(cl.peers())} for n, cl in clients.items()}

    topo = topology()
    print("topology: " + json.dumps(topo))
    if topo["b"]["parent"] is not None:
        raise RuntimeError("B is not the root; premise changed")
    if topo["d"]["parent"] != "c":
        raise RuntimeError("D is not under C; premise changed")
    if topo["a"]["parent"] != "b":
        # A raced to C first; force it to B while keeping the A-C link for the
        # bypass arm, then let the link return (parent choice is sticky).
        print("forcing A's parent to B; current parent is "
              + str(topo["a"]["parent"]))
        write_acl(NODES["a"], [npub["b"]])
        time.sleep(0.8)
        exp_c.docker_exec(NODES["a"], ["fipsctl", "disconnect", npub["c"]])
        waited, _ = exp_c.wait_for(
            lambda: parent_name(clients["a"], name_of) == "b", 30)
        if waited is None:
            raise RuntimeError("A did not re-parent to B")
        write_acl(NODES["a"], [npub["b"], npub["c"]])
        exp_c.wait_for(lambda: exp_c.peer_for(clients["a"], npub["c"]), 30)
        topo = topology()
        print("forced topology: " + json.dumps(topo))
        if topo["a"]["parent"] != "b":
            raise RuntimeError("A did not stay under B")

    block_b = control(NODES["b"], npub["a"], allow=False)
    time.sleep(0.5)
    after_block = {
        "a_to_d": exp_c.ping6(NODES["a"], d_addr, count=3),
        "a_to_b": exp_c.ping6(NODES["a"], status["b"]["ipv6_addr"], count=3),
        "a_to_c": exp_c.ping6(NODES["a"], status["c"]["ipv6_addr"], count=3),
        "c_to_d": exp_c.ping6(NODES["c"], d_addr, count=3),
        "link_a_b": exp_c.peer_for(clients["b"], npub["a"]) is not None,
    }
    print("blocked at B: " + json.dumps({
        k: (v if isinstance(v, bool) else v.get("ok"))
        for k, v in after_block.items()}))

    # Force A to re-parent to C by denying B on A and disconnecting A-B.
    write_acl(NODES["a"], [npub["c"]])
    time.sleep(0.8)
    cmd = exp_c.docker_exec(NODES["a"], ["fipsctl", "disconnect", npub["b"]])
    print(f"disconnect A-B: {cmd.returncode} {cmd.stdout.strip()[:80]}")
    reparent_start = time.monotonic()
    waited, _ = exp_c.wait_for(
        lambda: parent_name(clients["a"], name_of) == "c", 30)
    reparent_ms = None
    if waited is not None:
        reparent_ms = round((time.monotonic() - reparent_start) * 1000)
    topo_after = topology()
    print("after re-parent: " + json.dumps({"topology": topo_after,
                                            "parent_c_ms": reparent_ms}))

    bypass = exp_c.ping6(NODES["a"], d_addr, count=3)
    print("bypass a->d via C: " + json.dumps(bypass))

    # Block A at C as well; the alternate path must close.
    block_c = control(NODES["c"], npub["a"], allow=False)
    time.sleep(0.5)
    blocked_both = exp_c.ping6(NODES["a"], d_addr, count=3)
    print("blocked at B and C: " + json.dumps(blocked_both))

    cycles = []
    for i in range(CYCLES):
        allow_c = control(NODES["c"], npub["a"], allow=True)
        time.sleep(0.4)
        ok = exp_c.ping6(NODES["a"], d_addr, count=3)
        block_c = control(NODES["c"], npub["a"], allow=False)
        time.sleep(0.4)
        bad = exp_c.ping6(NODES["a"], d_addr, count=3)
        cycles.append({"cycle": i + 1, "allow_ok": ok["ok"],
                       "block_ok": bad["ok"],
                       "allow_loss": ok["loss_pct"],
                       "block_loss": bad["loss_pct"]})
        print("cycle: " + json.dumps(cycles[-1]))

    out = {
        "date": time.strftime("%Y-%m-%d"),
        "baseline": {"a_to_d": baseline_ad["ok"], "c_to_d": baseline_cd["ok"]},
        "topology": topo,
        "block_at_b": {
            "response": block_b,
            "a_to_d_ok": after_block["a_to_d"]["ok"],
            "a_to_d_loss_pct": after_block["a_to_d"]["loss_pct"],
            "a_to_b_ok": after_block["a_to_b"]["ok"],
            "a_to_c_ok": after_block["a_to_c"]["ok"],
            "c_to_d_ok": after_block["c_to_d"]["ok"],
            "link_a_b": after_block["link_a_b"],
        },
        "reparent": {"to": parent_name(clients["a"], name_of),
                     "ms": reparent_ms, "topology": topo_after},
        "bypass_via_c": {"ok": bypass["ok"], "loss_pct": bypass["loss_pct"]},
        "blocked_both": {"ok": blocked_both["ok"],
                         "loss_pct": blocked_both["loss_pct"]},
        "cycles_at_c": cycles,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
