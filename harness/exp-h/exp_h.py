#!/usr/bin/env python3
"""Exp H: can an ACL deny of the current parent force re-parenting?

Three-node triangle, each node directly peered with the other two. The tree
picks one parent per node. We deny the deepest non-root node's current parent on
that parent's ACL, disconnect the parent link, and watch whether the child
re-parents to its alternate peer.

Run from the host with PYTHONPATH=sidecar.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.runner import DockerRunner, RunnerError

NODES = {"p": "lt-exp-h-p", "x": "lt-exp-h-x", "q": "lt-exp-h-q"}


def docker_exec(container: str, argv, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container, *argv],
        capture_output=True, text=True, timeout=timeout,
    )


def wait_for(predicate, timeout: float, interval: float = 0.05):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        value = predicate()
        if value:
            return time.monotonic() - started, value
        time.sleep(interval)
    return None, None


def write_acl(container: str, allows: List[str]) -> None:
    allow = ("\n".join(allows) + "\n") if allows else ""
    deny = "ALL\n"
    code = (
        "import pathlib; "
        "pathlib.Path('/etc/fips/peers.allow').write_text(%r); "
        "pathlib.Path('/etc/fips/peers.deny').write_text(%r)"
    ) % (allow, deny)
    result = docker_exec(container, ["python3", "-c", code])
    if result.returncode != 0:
        raise RuntimeError(f"ACL write failed: {result.stderr.strip()}")


def acl_show(container: str) -> Dict[str, Any]:
    result = docker_exec(container, ["fipsctl", "acl", "show"])
    if result.returncode != 0:
        raise RuntimeError(f"fipsctl acl show failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def measure_acl(container: str, allows: List[str], timeout: float = 5.0):
    write_acl(container, allows)
    expected = set(allows)
    elapsed, state = wait_for(
        lambda: (lambda s: s if set(s.get("allow_entries", [])) == expected
                 and s.get("deny_all") else None)(acl_show(container)),
        timeout,
    )
    if elapsed is None:
        raise RuntimeError(f"ACL did not reach {sorted(expected)} within {timeout}s")
    return elapsed, state


def running(fips: Fipsctl):
    try:
        status = fips.status()
    except RunnerError:
        return None
    return status if status.get("state") == "running" else None


def peer_for(fips: Fipsctl, npub: str) -> Optional[Dict[str, Any]]:
    for peer in fips.peers():
        if peer.get("npub") == npub:
            return peer
    return None


def parent_npub(fips: Fipsctl) -> Optional[str]:
    for peer in fips.peers():
        if peer.get("is_parent"):
            return peer.get("npub")
    return None


def status_is_root(fips: Fipsctl) -> bool:
    try:
        return bool(fips.status().get("is_root"))
    except RunnerError:
        return False


def ping6(container: str, addr: str, count: int = 3, timeout: int = 1) -> Dict[str, Any]:
    result = docker_exec(
        container,
        ["ping6", "-c", str(count), "-W", str(timeout), addr],
        timeout=count * timeout + 15,
    )
    loss = None
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", result.stdout)
    if match:
        loss = float(match.group(1))
    return {
        "ok": result.returncode == 0,
        "loss_pct": loss,
        "stdout": result.stdout.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deny-hold", type=float, default=3.0)
    parser.add_argument("--observe", type=float, default=20.0)
    args = parser.parse_args()

    fips = {name: Fipsctl(DockerRunner(container)) for name, container in NODES.items()}

    for name, client in fips.items():
        elapsed, _ = wait_for(lambda c=client: running(c), 20)
        if elapsed is None:
            raise RuntimeError(f"{name} daemon did not come up")

    status = {name: client.status() for name, client in fips.items()}
    npub = {name: s["npub"] for name, s in status.items()}
    name_of = {v: k for k, v in npub.items()}
    print("nodes:", json.dumps(npub, indent=2))

    # Strict ACLs on all three. P is passive; X and Q dial it and each other.
    acl_ms = {}
    acl_ms["p"] = measure_acl(NODES["p"], [npub["x"], npub["q"]])[0]
    acl_ms["x"] = measure_acl(NODES["x"], [npub["p"], npub["q"]])[0]
    acl_ms["q"] = measure_acl(NODES["q"], [npub["p"], npub["x"]])[0]
    print(f"ACL effective ms: { {k: round(v*1000) for k,v in acl_ms.items()} }")

    # Every node should have two direct peers.
    def triangle():
        counts = {name: len(client.peers()) for name, client in fips.items()}
        return counts if all(v >= 2 for v in counts.values()) else None

    elapsed, counts = wait_for(triangle, 30)
    if elapsed is None:
        print("FATAL: triangle did not form", file=sys.stderr)
        for name, client in fips.items():
            print(name, json.dumps(client.peers(), indent=2)[:1000], file=sys.stderr)
        return 2
    print(f"triangle formed in {elapsed*1000:.0f} ms: {counts}")

    def topology() -> Dict[str, Any]:
        out = {}
        for name, client in fips.items():
            peers = client.peers()
            parent = next((p for p in peers if p.get("is_parent")), None)
            children = [p.get("npub") for p in peers if p.get("is_child")]
            out[name] = {
                "npub": npub[name],
                "parent": parent.get("npub") if parent else None,
                "parent_name": name_of.get(parent.get("npub")) if parent else None,
                "children": [name_of.get(c, c) for c in children],
                "depth": (parent.get("effective_depth") or parent.get("tree_depth") or 0) if parent else 0,
                "is_root": status_is_root(client),
                "peers": len(peers),
            }
        return out

    topo_before = topology()
    print("topology before:", json.dumps(topo_before, indent=2))

    # Pick the deepest non-root node that has a parent and an alternate peer.
    candidates = []
    for name, info in topo_before.items():
        if info["parent"] and info["peers"] >= 2:
            peers = fips[name].peers()
            alt = next((p for p in peers if not p.get("is_parent")), None)
            if alt:
                candidates.append((info["depth"] or 0, name, info["parent"], alt.get("npub")))
    if not candidates:
        print("FATAL: no node with a parent and an alternate peer", file=sys.stderr)
        return 2
    depth, child, parent, alt = max(candidates, key=lambda item: item[0])
    child_name = child
    parent_name = name_of[parent]
    alt_name = name_of[alt]
    print(f"chosen child={child_name} depth={depth} parent={parent_name} "
          f"alternate={alt_name}")

    child_addr = status[child_name]["ipv6_addr"]
    parent_addr = status[parent_name]["ipv6_addr"]
    before_ping = ping6(NODES[child_name], parent_addr)
    print(f"ping {child_name}->{parent_name} before: ok={before_ping['ok']} "
          f"loss={before_ping['loss_pct']}%")

    # Deny the child on the parent, then disconnect. In a triangle this
    # leaves exactly the third node in the parent's allowlist.
    parent_allows = [n for n in npub.values()
                     if n not in (npub[child_name], npub[parent_name])]
    acl_deny_ms, _ = measure_acl(NODES[parent_name], parent_allows)
    print(f"deny {child_name} on {parent_name}: ACL effective in {acl_deny_ms*1000:.0f} ms; "
          f"allow={ [name_of[n] for n in parent_allows] }")

    cut_started = time.monotonic()
    fips[parent_name].disconnect(npub[child_name])
    cmd_ms = (time.monotonic() - cut_started) * 1000
    print(f"disconnect {child_name} on {parent_name}: {cmd_ms:.0f} ms")

    # Watch the child's parent.
    transitions = []
    last_parent = parent
    reparent_started = time.monotonic()
    success = False
    became_root = False
    final_parent = last_parent
    while time.monotonic() - reparent_started < args.observe:
        current = parent_npub(fips[child_name])
        if current != last_parent:
            transitions.append({
                "at_ms": round((time.monotonic() - cut_started) * 1000),
                "from": name_of.get(last_parent),
                "to": name_of.get(current),
            })
            last_parent = current
            final_parent = current
        if current == npub[alt_name]:
            success = True
            break
        if current is None and status_is_root(fips[child_name]):
            became_root = True
            break
        time.sleep(0.05)

    reparent_ms = (time.monotonic() - cut_started) * 1000
    print(f"re-parent: success_to_{alt_name}={success} became_root={became_root} "
          f"final_parent={name_of.get(final_parent)} at {reparent_ms:.0f} ms")
    print(f"transitions: {transitions}")

    # Let the tree settle, then check routing.
    time.sleep(1.0)
    topo_after = topology()
    print("topology after:", json.dumps(topo_after, indent=2))
    after_ping = ping6(NODES[child_name], parent_addr)
    alt_ping = ping6(NODES[alt_name], parent_addr)
    print(f"ping {child_name}->{parent_name} after: ok={after_ping['ok']} "
          f"loss={after_ping['loss_pct']}%")
    print(f"ping {alt_name}->{parent_name}: ok={alt_ping['ok']} "
          f"loss={alt_ping['loss_pct']}%")

    # Re-admit on the parent and see whether the child returns.
    acl_allow_ms, _ = measure_acl(
        NODES[parent_name], [n for k, n in npub.items() if k != parent_name])
    readmit_started = time.monotonic()
    elapsed, _ = wait_for(
        lambda: peer_for(fips[parent_name], npub[child_name]) and
                peer_for(fips[child_name], npub[parent_name]),
        5,
    )
    readmit_mode = "auto"
    if elapsed is None:
        readmit_mode = "explicit"
        docker_exec(NODES[child_name],
                    ["fipsctl", "connect", npub[parent_name],
                     f"{parent_name}:2121", "udp"])
        elapsed, _ = wait_for(
            lambda: peer_for(fips[parent_name], npub[child_name]) and
                    peer_for(fips[child_name], npub[parent_name]),
            15,
        )
    if elapsed is None:
        print("FATAL: re-admit did not restore the link", file=sys.stderr)
        return 2
    link_readmit_ms = (time.monotonic() - readmit_started) * 1000
    time.sleep(1.0)
    topo_readmit = topology()
    readmit_ping = ping6(NODES[child_name], parent_addr)
    print(f"re-admit: mode={readmit_mode} total={acl_allow_ms*1000 + link_readmit_ms:.0f} ms "
          f"(acl {acl_allow_ms*1000:.0f} + link {link_readmit_ms:.0f})")
    print("topology after re-admit:", json.dumps(topo_readmit, indent=2))
    print(f"ping after re-admit: ok={readmit_ping['ok']} loss={readmit_ping['loss_pct']}%")

    summary = {
        "date": datetime.date.today().isoformat(),
        "fips_version": status["p"].get("version"),
        "nodes": npub,
        "acl_ms": {k: round(v * 1000) for k, v in acl_ms.items()},
        "chosen": {
            "child": child_name,
            "parent": parent_name,
            "alternate": alt_name,
            "depth": depth,
        },
        "before": topo_before,
        "cut": {
            "acl_deny_ms": round(acl_deny_ms * 1000),
            "disconnect_cmd_ms": round(cmd_ms),
            "observed_ms": round(reparent_ms),
            "reparent_to_alternate": success,
            "became_root": became_root,
            "final_parent": name_of.get(final_parent),
            "transitions": transitions,
            "ping_child_to_parent_before": before_ping["ok"],
            "ping_child_to_parent_after": after_ping["ok"],
        },
        "after": topo_after,
        "readmit": {
            "mode": readmit_mode,
            "acl_ms": round(acl_allow_ms * 1000),
            "link_ms": round(link_readmit_ms),
            "total_ms": round(acl_allow_ms * 1000 + link_readmit_ms),
            "topology": topo_readmit,
            "ping_child_to_parent": readmit_ping["ok"],
        },
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
