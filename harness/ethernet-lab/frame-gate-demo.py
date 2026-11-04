#!/usr/bin/env python3
"""FrameGate module against real nftables.

Runs inside the E4 image with the sidecar mounted. The module (not hand-written
nft commands) installs the table and drives the policy:

  1. rate-limit only: A under the bucket, B and C each capped;
  2. block(B): B stops, C unaffected; unblock restores B;
  3. default_deny: only authorised MACs pass; authorising B restores it.

The receiver counts survivors per source MAC behind a bridge, so dropped frames
are invisible to it (AF_PACKET on the gate interface would see pre-hook traffic).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time

from tollgate_fips.frame_gate import FrameGate, FrameGateConfig, SubprocessNft

S0, S1 = "fgs0", "fgs1"
D0, D1 = "fgd0", "fgd1"
BR = "fgbr"

MAC_A = "02:00:00:00:00:0a"
MAC_B = "02:00:00:00:00:0b"
MAC_C = "02:00:00:00:00:0c"
RATES = {"a": 500, "b": 5000, "c": 5000}
SECONDS = 3.0
BUCKET = {"interface": S1, "rate_pps": 1000, "burst": 100, "timeout": "10m"}


def run(argv, check=True):
    return subprocess.run(argv, check=check, text=True,
                          capture_output=True)


def cleanup_links():
    for link in (S0, D0, BR):
        run(["ip", "link", "del", link], check=False)


def setup_links():
    cleanup_links()
    run(["ip", "link", "add", S0, "type", "veth", "peer", "name", S1])
    run(["ip", "link", "add", D0, "type", "veth", "peer", "name", D1])
    run(["ip", "link", "add", BR, "type", "bridge"])
    for dev in (S0, S1, D0, D1, BR):
        run(["ip", "link", "set", dev, "up"])
    run(["ip", "link", "set", S1, "master", BR])
    run(["ip", "link", "set", D0, "master", BR])
    time.sleep(0.5)


def parse_recv(text):
    per = {}
    for match in re.finditer(r"^mac ([0-9a-f:]+) (\d+)$", text, re.M):
        per[match.group(1)] = int(match.group(2))
    return per


def traffic(senders):
    """Run `senders` ({name: (mac, pps)}) against the receiver; return counts."""
    receiver = subprocess.Popen(
        ["bench", "recvmac", D1, str(SECONDS + 0.8)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.25)
    procs = {name: subprocess.Popen(
        ["bench", "send", S0, str(pps), str(SECONDS), "64", mac],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for name, (mac, pps) in senders.items()}
    sent = {}
    for name, proc in procs.items():
        out, _ = proc.communicate(timeout=SECONDS + 15)
        match = re.search(r"sent (\d+)", out)
        sent[name] = int(match.group(1)) if match else 0
    recv_out, _ = receiver.communicate(timeout=SECONDS + 15)
    per = parse_recv(recv_out)
    return {
        "sent": sent,
        "recv": {name: per.get(mac, 0) for name, (mac, _) in senders.items()},
    }


def main() -> int:
    setup_links()
    gate = FrameGate(SubprocessNft(), FrameGateConfig(**BUCKET))
    summary = {"bucket": BUCKET, "seconds": SECONDS, "macs": {
        "a": MAC_A, "b": MAC_B, "c": MAC_C}}
    try:
        # 1. Per-MAC rate limit only.
        gate.install()
        summary["ratelimit"] = traffic({
            "a": (MAC_A, RATES["a"]),
            "b": (MAC_B, RATES["b"]),
            "c": (MAC_C, RATES["c"]),
        })
        summary["buckets"] = sorted(gate.buckets())
        summary["status_has_counters"] = any(
            "counter" in str(rule)
            for item in gate.status().get("nftables", [])
            for rule in (item.get("rule", {}).get("expr", [])
                         if isinstance(item.get("rule"), dict) else []))

        # 2. Explicit block of B; C must be unaffected.
        gate.block(MAC_B)
        summary["blocked"] = traffic({
            "b": (MAC_B, RATES["b"]),
            "c": (MAC_C, RATES["c"]),
        })
        gate.unblock(MAC_B)
        summary["unblocked"] = traffic({"b": (MAC_B, RATES["b"])})

        # 3. Allow-list mode. A and B are unknown until authorised.
        gate.config.default_deny = True
        gate.install()
        gate.authorise(MAC_A)
        summary["allowlist_before_b"] = traffic({
            "a": (MAC_A, RATES["a"]),
            "b": (MAC_B, RATES["b"]),
        })
        gate.authorise(MAC_B)
        summary["allowlist_after_b"] = traffic({"b": (MAC_B, RATES["b"])})
    finally:
        gate.uninstall()
        cleanup_links()

    print(json.dumps(summary, indent=2))

    r = summary
    ok = (
        r["ratelimit"]["recv"] == {"a": 1500, "b": 3099, "c": 3099}
        # The dynamic set creates an element for every sender on its first
        # frame, so A is present even though it is under the rate. Presence
        # is "seen", not "over the limit"; the receive counts above are what
        # prove A was not dropped.
        and r["buckets"] == [MAC_A, MAC_B, MAC_C]
        and r["status_has_counters"]
        and r["blocked"]["recv"]["b"] == 0
        and r["blocked"]["recv"]["c"] == 3099
        and 3000 <= r["unblocked"]["recv"]["b"] <= 3200
        and r["allowlist_before_b"]["recv"]["a"] == 1500
        and r["allowlist_before_b"]["recv"]["b"] == 0
        and 3000 <= r["allowlist_after_b"]["recv"]["b"] <= 3200
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
