#!/usr/bin/env bash
# Sample FIPS counters twice and report deltas.
#
# Usage:
#   sample-counters.sh <host> [seconds] [via-host]
#
#   sample-counters.sh host-a 5
#   sample-counters.sh host-a 5 c03rad0r@gateway.example
#
# Read-only. Writes nothing to the remote host.
set -euo pipefail

HOST=${1:?usage: sample-counters.sh <host> [seconds] [via-host]}
SECS=${2:-5}
VIA=${3:-}

remote() {
  if [ -n "$VIA" ]; then
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$VIA" \
      "ssh -o BatchMode=yes -o ConnectTimeout=8 $HOST '$1'"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" "$1"
  fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

remote 'fipsctl show transports' >"$TMP/t0.json"
remote 'fipsctl show links' >"$TMP/l0.json"
sleep "$SECS"
remote 'fipsctl show transports' >"$TMP/t1.json"
remote 'fipsctl show links' >"$TMP/l1.json"

python3 - "$TMP" "$SECS" "$HOST" <<'PY'
import json, sys
tmp, secs, host = sys.argv[1], float(sys.argv[2]), sys.argv[3]

def load(name):
    with open(f"{tmp}/{name}") as f:
        return json.load(f)

t0, t1 = load("t0.json"), load("t1.json")
l0, l1 = load("l0.json"), load("l1.json")

print(f"host={host} window={secs:.1f}s")
print("\ntransports (delta, rate, mean frame size):")
for a, b in zip(t0.get("transports", []), t1.get("transports", [])):
    sa, sb = a.get("stats", {}), b.get("stats", {})
    dbytes = sb.get("bytes_sent", 0) + sb.get("bytes_recv", 0) \
        - sa.get("bytes_sent", 0) - sa.get("bytes_recv", 0)
    dpkts = sb.get("packets_sent", 0) + sb.get("packets_recv", 0) \
        - sa.get("packets_sent", 0) - sa.get("packets_recv", 0)
    bps = dbytes / secs if secs else 0
    mean = dbytes / dpkts if dpkts else 0
    print(f"  id={a.get('transport_id')} type={a.get('type'):8s} "
          f"bytes={dbytes:>12d} pkts={dpkts:>8d} rate={bps/1000:8.1f} kB/s "
          f"mean_frame={mean:6.1f} B")

print("\nlinks (delta bytes, from per-peer stats):")
by_id = {}
for a, b in zip(l0.get("links", []), l1.get("links", [])):
    sa, sb = a.get("stats", {}), b.get("stats", {})
    d = sb.get("bytes_sent", 0) + sb.get("bytes_recv", 0) \
        - sa.get("bytes_sent", 0) - sa.get("bytes_recv", 0)
    by_id[a.get("link_id")] = d
    print(f"  link={a.get('link_id')} tid={a.get('transport_id')} "
          f"addr={a.get('remote_addr')} bytes={d}")
print(f"\nsum(link delta)={sum(by_id.values())}")
PY

cat <<'NOTE'

Boundary note:
  These counters are FMP frame bytes at the transport API -- the datagram
  handed to / returned from the socket. They include the FMP common prefix,
  the remaining header and the AEAD tag, and they exclude medium
  encapsulation (UDP 8 + IPv6 40, TCP 20 + 20, Ethernet 14).
NOTE
