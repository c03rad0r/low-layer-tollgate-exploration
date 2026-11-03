#!/usr/bin/env python3
"""Frame-gate throughput: nft netdev drop/accept vs a userspace receiver.

Runs inside the benchmark image with NET_ADMIN + NET_RAW and --network none.
Builds a veth pair, then for each mode and target rate sends 0x2121 frames for
a fixed window and records:

  sent     frames the sender managed to emit
  seen     nft counter (drop/accept) or userspace received frames
  busy%    host-wide non-idle CPU delta over the window (all CPUs)

The nft cases drop or accept before any socket, so userspace is not involved.
The userspace case removes the table and reads the frames from v0.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import sys

V0 = "fg0"
V1 = "fg1"
TABLE = "fg"
CHAIN = "ingress"


def run(argv, check=True):
    return subprocess.run(argv, check=check, text=True, capture_output=True)


def setup_links():
    run(["ip", "link", "del", V0], check=False)
    run(["ip", "link", "add", V0, "type", "veth", "peer", "name", V1])
    run(["ip", "link", "set", V0, "up"])
    run(["ip", "link", "set", V1, "up"])


def cleanup_nft():
    run(["nft", "delete", "table", "netdev", TABLE], check=False)


def install_rule(verdict: str):
    cleanup_nft()
    run(["nft", "add", "table", "netdev", TABLE])
    run(["nft", "add", "chain", "netdev", TABLE, CHAIN,
         "{", "type", "filter", "hook", "ingress", "device", V0,
         "priority", "0", ";", "}"])
    run(["nft", "add", "rule", "netdev", TABLE, CHAIN,
         "ether", "type", "0x2121", "counter", verdict])


def counter_packets() -> int:
    out = run(["nft", "list", "chain", "netdev", TABLE, CHAIN]).stdout
    match = re.search(r"counter packets (\d+)", out)
    return int(match.group(1)) if match else 0


def cpu_busy():
    with open("/proc/stat") as handle:
        line = handle.readline()
    parts = [int(x) for x in line.split()[1:]]
    idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
    return sum(parts) - idle, sum(parts)


def send_case(rate: int, seconds: float, size: int) -> dict:
    busy_before, total_before = cpu_busy()
    started = time.monotonic()
    out = run(["bench", "send", V1, str(rate), str(seconds), str(size)]).stdout
    elapsed = time.monotonic() - started
    busy_after, total_after = cpu_busy()
    sent = int(re.search(r"sent (\d+)", out).group(1))
    busy = (busy_after - busy_before) / max(1, total_after - total_before) * 100
    return {"sent": sent, "elapsed_s": round(elapsed, 3),
            "sent_pps": round(sent / elapsed), "host_busy_pct": round(busy, 1)}


def userspace_case(rate: int, seconds: float, size: int) -> dict:
    busy_before, total_before = cpu_busy()
    receiver = subprocess.Popen(
        ["bench", "recv", V0, str(seconds + 0.5)],
        stdout=subprocess.PIPE, text=True)
    time.sleep(0.2)
    started = time.monotonic()
    out = run(["bench", "send", V1, str(rate), str(seconds), str(size)]).stdout
    elapsed = time.monotonic() - started
    recv_out = receiver.communicate(timeout=seconds + 10)[0]
    busy_after, total_after = cpu_busy()
    sent = int(re.search(r"sent (\d+)", out).group(1))
    received = int(re.search(r"recv (\d+)", recv_out).group(1))
    busy = (busy_after - busy_before) / max(1, total_after - total_before) * 100
    return {"sent": sent, "received": received,
            "elapsed_s": round(elapsed, 3),
            "sent_pps": round(sent / elapsed),
            "recv_pps": round(received / elapsed),
            "host_busy_pct": round(busy, 1)}


def main() -> int:
    rates = [1000, 10000, 100000]
    seconds = 2.0
    size = 64
    if len(sys.argv) > 1:
        rates = [int(x) for x in sys.argv[1].split(",")]
    if len(sys.argv) > 2:
        seconds = float(sys.argv[2])

    setup_links()
    results = {"rates": rates, "seconds": seconds, "frame_bytes": size,
               "cases": {}}
    try:
        for verdict in ("drop", "accept"):
            install_rule(verdict)
            rows = []
            for rate in rates:
                before = counter_packets()
                row = send_case(rate, seconds, size)
                after = counter_packets()
                row.update({"rate": rate, "verdict": verdict,
                            "counter_delta": after - before,
                            "counter_pps": round((after - before) / row["elapsed_s"])})
                rows.append(row)
            results["cases"][f"nft_{verdict}"] = rows

        cleanup_nft()
        rows = []
        for rate in rates:
            rows.append(dict(userspace_case(rate, seconds, size), rate=rate,
                             verdict="userspace"))
        results["cases"]["userspace"] = rows
    finally:
        cleanup_nft()
        run(["ip", "link", "del", V0], check=False)

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
