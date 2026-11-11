#!/usr/bin/env python3
"""Run the live two-client FIPS application relay sequence."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))

import exp_c
from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.runner import DockerRunner

A, B, C = "lt-app-a", "lt-app-b", "lt-app-c"
COUNT = 10


def sh(args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)


def main() -> int:
    # Compose volumes do not remove this lab's bind-mounted journals on restart.
    reset = subprocess.run([
        "docker", "run", "--rm", "-v", "/tmp/opencode/fips-app-out:/out",
        "alpine:3.20", "sh", "-c", "rm -rf /out/*"],
        text=True, capture_output=True)
    if reset.returncode != 0:
        raise RuntimeError(f"could not clear lab state: {reset.stderr}")
    fips = {name: Fipsctl(DockerRunner(container))
            for name, container in (("a", A), ("b", B), ("c", C))}
    for name, cl in fips.items():
        if exp_c.wait_for(lambda c=cl: exp_c.running(c), 30)[0] is None:
            raise RuntimeError(f"{name} FIPS process did not start")
    status = {name: cl.status() for name, cl in fips.items()}
    npubs = {name: status[name]["npub"] for name in fips}
    for x, y in (("a", "b"), ("c", "b")):
        waited, _ = exp_c.wait_for(
            lambda x=x, y=y: (exp_c.peer_for(fips[x], npubs[y])
                              and exp_c.peer_for(fips[y], npubs[x])), 30)
        if waited is None:
            raise RuntimeError(f"FIPS link {x}-{y} did not form")
        print(f"link {x}-{y} up in {waited*1000:.0f} ms")

    out = Path("/tmp/opencode/fips-app-out/service-result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    sh(["docker", "exec", "-d", B, "python3", "/app/server.py", str(COUNT)])
    time.sleep(1)

    def send(node, kind, *args):
        stdout = sh(["docker", "exec", node, "python3", "/app/client.py",
                     status["b"]["ipv6_addr"], kind, *args]).stdout
        parsed = json.loads(stdout)
        print(json.dumps(parsed))
        return parsed

    send(A, "pay", "live-1", "1000")
    send(C, "pay", "live-1", "1000")       # another peer, same proof
    send(C, "pay", "live-2", "1000")       # the valid first payment for C
    send(A, "frame", "100")                # allowed, remaining 990
    send(C, "frame", "100")                # allowed, remaining 990
    send(A, "frame", "9900")               # now grace, remaining 0
    send(A, "frame", "10")                 # exhausted
    send(A, "pay", "live-3", "2000")       # correct renewal
    send(A, "link_down", "one")             # preserve credit, DORMANT
    send(A, "frame", "100")                # authenticated resumed link restores credit

    for _ in range(30):
        if out.exists():
            records = json.loads(out.read_text())
            if len(records) == COUNT:
                break
        time.sleep(0.5)
    records = json.loads(out.read_text())
    print(json.dumps(records, indent=2))
    actions = [row["response"] for row in records]
    expected = [
        ("ack", True), ("nack", False), ("ack", True), ("frame_result", True),
        ("frame_result", True), ("frame_result", True), ("frame_result", False),
        ("ack", True), ("ack", True), ("frame_result", True),
    ]
    for item, (kind, allowed) in zip(actions, expected):
        if item["t"] != kind:
            raise AssertionError(item)
        if kind == "frame_result" and item.get("allowed") is not allowed:
            raise AssertionError(item)
        if item["t"] == "nack" and item["code"] != "reservation_in_flight":
            raise AssertionError(item)
    assert records[0]["response"]["remaining_msat"] == "1000"
    assert records[3]["response"]["remaining_msat"] == "990"
    assert records[4]["response"]["remaining_msat"] == "990"
    assert records[5]["response"]["state"] == "grace"
    assert records[6]["response"]["remaining_msat"] == "0"
    assert records[6]["response"]["charged_msat"] == "0"
    assert records[8]["response"]["state"] == "dormant"
    assert records[9]["response"]["remaining_msat"] == "1990"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
