#!/usr/bin/env python3
"""Exp E4: per-source-MAC token bucket, nft vs tc-police vs tc/BPF.

Topology (so the receiver sees only frames that survived the gate):

    s0 (sender) == s1 (gate ingress) -- br0 -- d0 == d1 (receiver)

Two senders run concurrently with different source MACs:

    A  500 pps   (under the bucket)
    B 5000 pps   (over the bucket)
    C 5000 pps   (over the bucket, different MAC)

Bucket: 1000 pps, burst 100 frames. In the control run all three should
arrive intact; with a per-MAC bucket A should be untouched and B and C should
each be limited to roughly the bucket rate. A global (single) bucket would
throttle A and/or give B and C one shared allowance, which is the failure this
test looks for.

Modes:
  none  no gate
  nft   netdev ingress, dynamic set + `limit rate over`
  tc    clsact + one flower `police` filter per source MAC
  bpf   clsact + the token-bucket BPF classifier (LRU hash keyed by MAC)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time

S0, S1 = "e4s0", "e4s1"
D0, D1 = "e4d0", "e4d1"
BR = "e4br"
TABLE = "e4"

MAC_A = "02:00:00:00:00:0a"
MAC_B = "02:00:00:00:00:0b"
MAC_C = "02:00:00:00:00:0c"
RATE_A = 500
RATE_B = 5000
RATE_C = 5000
SECONDS = 3.0
BUCKET_PPS = 1000
BUCKET_BURST = 100
# tc `police` accounts ~50 B of a 64 B frame (it excludes the 14 B MAC header),
# so 400 kbit/s = 50 B * 8 * 1000 pps. Burst 5 kB ~= 100 frames.
TC_RATE = "400kbit"
TC_BURST = "5k"


def run(argv, check=True):
    return subprocess.run(argv, check=check, text=True, capture_output=True)


def try_run(argv):
    return subprocess.run(argv, check=False, text=True, capture_output=True)


def cleanup():
    try_run(["nft", "delete", "table", "netdev", TABLE])
    for dev in (S1, D0):
        try_run(["tc", "qdisc", "del", "dev", dev, "clsact"])
    for link in (S0, D0, BR):
        try_run(["ip", "link", "del", link])


def setup():
    cleanup()
    run(["ip", "link", "add", S0, "type", "veth", "peer", "name", S1])
    run(["ip", "link", "add", D0, "type", "veth", "peer", "name", D1])
    run(["ip", "link", "add", BR, "type", "bridge"])
    for dev in (S0, S1, D0, D1, BR):
        run(["ip", "link", "set", dev, "up"])
    run(["ip", "link", "set", S1, "master", BR])
    run(["ip", "link", "set", D0, "master", BR])
    # Let the bridge start forwarding.
    time.sleep(0.5)


def install_nft():
    run(["nft", "add", "table", "netdev", TABLE])
    # A timeout bounds idle state. Only over-limit MACs get an element, but a
    # busy AP would otherwise accumulate them until the set fills.
    run(["nft", "add", "set", "netdev", TABLE, "bucket",
         "{", "type", "ether_addr", ";", "flags", "dynamic", ";",
         "size", "65535", ";", "timeout", "10m", ";", "}"])
    run(["nft", "add", "chain", "netdev", TABLE, "ingress",
         "{", "type", "filter", "hook", "ingress", "device", S1,
         "priority", "0", ";", "}"])
    run(["nft", "add", "rule", "netdev", TABLE, "ingress",
         "ether", "type", "0x2121", "update", "@bucket",
         "{", "ether", "saddr", "limit", "rate", "over",
         f"{BUCKET_PPS}/second", "burst", str(BUCKET_BURST), "packets", "}",
         "counter", "drop"])
    run(["nft", "add", "rule", "netdev", TABLE, "ingress",
         "ether", "type", "0x2121", "counter", "accept"])


def install_tc():
    run(["tc", "qdisc", "add", "dev", S1, "clsact"])
    for mac in (MAC_A, MAC_B, MAC_C):
        run(["tc", "filter", "add", "dev", S1, "ingress",
             "protocol", "0x2121", "flower", "src_mac", mac,
             "action", "police", "rate", TC_RATE, "burst", TC_BURST,
             "drop"])


def install_bpf():
    run(["tc", "qdisc", "add", "dev", S1, "clsact"])
    result = try_run(["tc", "filter", "add", "dev", S1, "ingress",
                      "bpf", "da", "obj", "/usr/local/lib/token-bucket.o",
                      "sec", "classifier"])
    if result.returncode != 0:
        raise RuntimeError(f"bpf attach failed: {result.stderr.strip()}")


def parse_recv(text):
    per = {}
    for match in re.finditer(r"^mac ([0-9a-f:]+) (\d+)$", text, re.M):
        per[match.group(1)] = int(match.group(2))
    total = re.search(r"^total (\d+)$", text, re.M)
    return per, int(total.group(1)) if total else None


def one_run(mode: str) -> dict:
    if mode == "nft":
        install_nft()
    elif mode == "tc":
        install_tc()
    elif mode == "bpf":
        install_bpf()

    receiver = subprocess.Popen(
        ["bench", "recvmac", D1, str(SECONDS + 0.8)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.25)
    senders = {
        "a": subprocess.Popen(["bench", "send", S0, str(RATE_A),
                               str(SECONDS), "64", MAC_A],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True),
        "b": subprocess.Popen(["bench", "send", S0, str(RATE_B),
                               str(SECONDS), "64", MAC_B],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True),
        "c": subprocess.Popen(["bench", "send", S0, str(RATE_C),
                               str(SECONDS), "64", MAC_C],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True),
    }
    sent = {}
    for name, proc in senders.items():
        out, err = proc.communicate(timeout=SECONDS + 15)
        match = re.search(r"sent (\d+)", out)
        sent[name] = int(match.group(1)) if match else 0
    recv_out, recv_err = receiver.communicate(timeout=SECONDS + 15)
    per, total = parse_recv(recv_out)

    # Forget the gate before the next case.
    if mode == "nft":
        try_run(["nft", "delete", "table", "netdev", TABLE])
    elif mode in ("tc", "bpf"):
        try_run(["tc", "qdisc", "del", "dev", S1, "clsact"])

    return {
        "mode": mode,
        "sent": {"a": sent["a"], "b": sent["b"], "c": sent["c"]},
        "recv": {"a": per.get(MAC_A, 0), "b": per.get(MAC_B, 0),
                 "c": per.get(MAC_C, 0)},
        "total": total,
        "recv_other_macs": {k: v for k, v in per.items()
                            if k not in (MAC_A, MAC_B, MAC_C)},
        "stderr": recv_err.strip(),
    }


def main() -> int:
    repeats = 3
    if len(sys.argv) > 1:
        repeats = int(sys.argv[1])

    setup()
    results = {}
    try:
        for mode in ("none", "nft", "tc", "bpf"):
            results[mode] = [one_run(mode) for _ in range(repeats)]
    finally:
        cleanup()

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "topology": f"{S0}=={S1}--{BR}--{D0}=={D1}",
        "macs": {"a": MAC_A, "b": MAC_B, "c": MAC_C},
        "rates_pps": {"a": RATE_A, "b": RATE_B, "c": RATE_C},
        "bucket": {"pps": BUCKET_PPS, "burst": BUCKET_BURST,
                   "tc_rate": TC_RATE, "tc_burst": TC_BURST},
        "seconds": SECONDS,
        "repeats": repeats,
        "results": results,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
