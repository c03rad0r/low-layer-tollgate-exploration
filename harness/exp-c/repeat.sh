#!/usr/bin/env bash
# Repeat Exp C N times from a clean compose project and summarise the runs.
#
# Usage:
#   harness/exp-c/repeat.sh [runs] [output-dir]
#
# Default: 3 runs, /tmp/opencode/exp-c-repeats-<epoch>.
# The raw human-readable logs stay in the output dir; summary.json is written
# beside them.
set -euo pipefail

N=${1:-3}
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT=${2:-/tmp/opencode/exp-c-repeats-$(date +%s)}
mkdir -p "$OUT"

for i in $(seq 1 "$N"); do
  echo "=== Exp C run $i/$N ==="
  docker compose -f "$HERE/docker-compose.yaml" down -v --remove-orphans >/dev/null 2>&1 || true
  if ! "$HERE/run-exp-c.sh" > "$OUT/run$i.txt" 2>&1; then
    echo "run $i failed; tail:" >&2
    tail -30 "$OUT/run$i.txt" >&2
    exit 1
  fi
  tail -2 "$OUT/run$i.txt"
done

python3 - "$OUT" <<'PY'
import json
import pathlib
import statistics
import sys

out = pathlib.Path(sys.argv[1])
runs = []
for path in sorted(out.glob("run*.txt")):
    text = path.read_text()
    start = text.rindex("\n{\n")
    runs.append(json.loads(text[start:]))

widths = (6, 10, 10, 12, 12, 12, 11, 12, 10)
print()
print(f"{'run':>6} {'acl':>10} {'down':>10} {'bare recon':>12} "
      f"{'dur ACL':>12} {'dur down':>12} {'readmit ACL':>11} "
      f"{'readmit link':>12} {'total':>10}")
for i, run in enumerate(runs, 1):
    e = run["exp_c"]
    nd, du = e["non_durable_cut"], e["durable_evict"]
    print(f"{i:>6} {run['acl']['initial_allow_ms']:>10} {nd['seller_down_ms']:>10} "
          f"{nd['reconnect_total_ms']:>12} {du['acl_wait_ms']:>12} "
          f"{du['seller_down_ms']:>12} {run['acl']['allow_readmit_ms']:>11} "
          f"{du['link_readmit_ms']:>12} {du['total_readmit_ms']:>10}")

def rng(values):
    return f"{min(values)}-{max(values)} (median {statistics.median(values):.0f})"

print()
print("ranges:")
print("  ACL allow initial :", rng([r["acl"]["initial_allow_ms"] for r in runs]), "ms")
print("  bare reconnect    :", rng([r["exp_c"]["non_durable_cut"]["reconnect_total_ms"] for r in runs]), "ms")
print("  durable ACL wait  :", rng([r["exp_c"]["durable_evict"]["acl_wait_ms"] for r in runs]), "ms")
print("  durable down      :", rng([r["exp_c"]["durable_evict"]["seller_down_ms"] for r in runs]), "ms")
print("  re-admit ACL      :", rng([r["acl"]["allow_readmit_ms"] for r in runs]), "ms")
print("  re-admit link     :", rng([r["exp_c"]["durable_evict"]["link_readmit_ms"] for r in runs]), "ms")
print("  re-admit total    :", rng([r["exp_c"]["durable_evict"]["total_readmit_ms"] for r in runs]), "ms")
print("  durable held      :", [(r["exp_c"]["durable_evict"]["held_s"],
                                 r["exp_c"]["durable_evict"]["seller_link_present"] or
                                 r["exp_c"]["durable_evict"]["buyer_link_present"]) for r in runs])
print("  link ids          :", [(r["exp_c"]["link_id_before"],
                                 r["exp_c"]["non_durable_cut"]["link_id_after"],
                                 r["exp_c"]["durable_evict"]["link_id_after"]) for r in runs])
(out / "summary.json").write_text(json.dumps(runs, indent=2) + "\n")
print(f"\nraw logs and summary.json: {out}")
PY
