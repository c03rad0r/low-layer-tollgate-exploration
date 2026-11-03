#!/usr/bin/env python3
"""Exp PRICE: does a local price penalty move the tree parent?

Diamond topology (patch c):

        r (root)
       / \\
      p1  p2
       \\  /
        l  (leaf)

`l` has two candidate parents, p1 and p2, both at depth 1. The tree already
compares effective depth with hysteresis; a local price on `l`'s current parent
should make the other candidate win on the next re-evaluation.

Runs three phases:
1. a small price (0.05) must not cross the hysteresis margin;
2. a large price (1.0) should move the parent;
3. clearing the price leaves the choice sticky (no forced revert).
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

NODES = {
    "r": "lt-price-r",
    "p1": "lt-price-p1",
    "p2": "lt-price-p2",
    "l": "lt-price-l",
}
PEERS = [("r", "p1"), ("r", "p2"), ("p1", "l"), ("p2", "l")]


def set_price(container: str, npub: str, price: str) -> dict:
    result = exp_c.docker_exec(
        container, ["fipsctl", "set-price", npub, price])
    if result.returncode != 0:
        raise RuntimeError(f"set-price failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def parent_of(client: Fipsctl):
    for peer in client.peers():
        if peer.get("is_parent"):
            return peer.get("npub")
    return None


def peer_names(client: Fipsctl):
    return {peer.get("npub"): peer.get("display_name")
            for peer in client.peers()}


def name_of(client: Fipsctl, npub):
    return peer_names(client).get(npub, npub)


def wait_parent_change(client: Fipsctl, before, timeout: float):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        current = parent_of(client)
        if current != before:
            return (time.monotonic() - started) * 1000, current
        time.sleep(0.1)
    return None, before


def main() -> int:
    clients = {name: Fipsctl(DockerRunner(container))
               for name, container in NODES.items()}
    for name, client in clients.items():
        if exp_c.wait_for(lambda c=client: exp_c.running(c), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")

    npub = {name: client.status()["npub"] for name, client in clients.items()}
    name_of_npub = {value: key for key, value in npub.items()}
    r_addr = clients["r"].status()["ipv6_addr"]

    # 1. Diamond links.
    for a, b in PEERS:
        if exp_c.wait_for(
            lambda a=a, b=b: exp_c.peer_for(clients[a], npub[b])
            and exp_c.peer_for(clients[b], npub[a]), 25,
        )[0] is None:
            raise RuntimeError(f"link {a}-{b} did not form")
    print("diamond links up")

    # 2. Warm MMP RTT on both candidate links: the tree only cost-compares
    # peers that have an SRTT, so an unmeasured parent cannot lose on price.
    for mid in ("p1", "p2"):
        addr = clients[mid].status()["ipv6_addr"]
        exp_c.ping6(NODES["l"], addr, count=3)
        exp_c.ping6(NODES[mid], clients["l"].status()["ipv6_addr"], count=3)

    # Warm identity/coords from the leaf to the root and wait for a parent.
    exp_c.docker_exec(NODES["l"], ["fipsctl", "probe", npub["r"]], timeout=40)
    if exp_c.wait_for(lambda: parent_of(clients["l"]) is not None, 25)[0] is None:
        raise RuntimeError("leaf never picked a parent")
    if exp_c.wait_for(lambda: len(clients["l"].peers()) >= 2, 10)[0] is None:
        raise RuntimeError("leaf has fewer than two peers")

    baseline = parent_of(clients["l"])
    baseline_name = name_of(clients["l"], baseline)
    other = next(p for p in (npub["p1"], npub["p2"]) if p != baseline)
    print(f"leaf parent baseline: {baseline_name}")

    # Default `node.tree.hold_down_secs` is 30: a discretionary switch is
    # suppressed for 30 s after the last one, and the leaf just picked this
    # parent. Wait it out so the price is the only variable.
    time.sleep(32.0)

    # 3. Small price must not cross the hysteresis margin.
    small = set_price(NODES["l"], baseline, "0.05")
    time.sleep(5.0)
    after_small = parent_of(clients["l"])
    small_held = after_small == baseline
    print(f"small price 0.05: parent={name_of(clients['l'], after_small)} "
          f"held={small_held}")

    # 4. Large price should move the parent.
    set_price(NODES["l"], baseline, "clear")
    time.sleep(1.0)
    large = set_price(NODES["l"], baseline, "1.0")
    switch_ms, after_large = wait_parent_change(
        clients["l"], baseline, timeout=40.0)
    large_moved = after_large == other
    print(f"large price 1.0: parent={name_of(clients['l'], after_large)} "
          f"moved={large_moved} in {switch_ms and round(switch_ms)} ms")

    # Routing must still work through the new parent.
    ping = exp_c.ping6(NODES["l"], r_addr, count=3)
    print(f"leaf->root after switch: ok={ping['ok']} loss={ping['loss_pct']}%")

    # 5. Clearing the price does not force a revert (sticky choice).
    set_price(NODES["l"], baseline, "clear")
    time.sleep(6.0)
    after_clear = parent_of(clients["l"])
    sticky = after_clear == after_large
    print(f"after clear: parent={name_of(clients['l'], after_clear)} "
          f"sticky={sticky}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": clients["r"].status().get("version"),
        "nodes": npub,
        "baseline_parent": baseline_name,
        "candidates": [name_of(clients["l"], npub["p1"]),
                       name_of(clients["l"], npub["p2"])],
        "small_price": {
            "value": 0.05,
            "response": small,
            "held": small_held,
            "parent_after": name_of(clients["l"], after_small),
        },
        "large_price": {
            "value": 1.0,
            "response": large,
            "moved": large_moved,
            "switch_ms": None if switch_ms is None else round(switch_ms),
            "parent_after": name_of(clients["l"], after_large),
        },
        "ping_leaf_to_root": {"ok": ping["ok"],
                              "loss_pct": ping["loss_pct"]},
        "after_clear": {
            "parent": name_of(clients["l"], after_clear),
            "sticky": sticky,
        },
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0 if (small_held and large_moved and ping["ok"] and sticky) else 1


if __name__ == "__main__":
    sys.exit(main())
