#!/usr/bin/env bash
# Repeat the pause/payment capstone N times and summarise the JSON summaries.
#
# Usage:
#   harness/pause/repeat-pay-demo.sh [runs] [output-dir] [--tcp]
set -euo pipefail

N=${1:-3}
OUT=${2:-/tmp/opencode/pd-repeats-$(date +%s)}
MODE=${3:-}
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$OUT"

if [ "$MODE" = "--tcp" ]; then
  RUNNER="$HERE/../pause-tcp/run-pay-demo.sh"
  COMPOSE="$HERE/../pause-tcp/docker-compose.yaml"
  LABEL=tcp
else
  RUNNER="$HERE/run-pay-demo.sh"
  COMPOSE="$HERE/docker-compose.yaml"
  LABEL=udp
fi

for i in $(seq 1 "$N"); do
  echo "=== PD/$LABEL run $i/$N ==="
  docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
  if ! "$RUNNER" > "$OUT/run$i.txt" 2>&1; then
    echo "run $i failed; tail:" >&2
    tail -30 "$OUT/run$i.txt" >&2
    exit 1
  fi
  tail -2 "$OUT/run$i.txt"
done

python3 - "$OUT" "$LABEL" <<'PY'
import json
import pathlib
import statistics
import sys

out = pathlib.Path(sys.argv[1])
label = sys.argv[2]
runs = []
for path in sorted(out.glob("run*.txt")):
    text = path.read_text()
    start = text.rindex("\n{\n")
    runs.append(json.loads(text[start:]))

def row(run):
    p = run["pause"]
    b = p["blocked_burst"]
    return {
        "wire": run["session"]["billable_bytes"],
        "pause_ms": p["pause_ms"],
        "link_ok": p["link_preserved"],
        "resume_link_ok": run["resume"]["link_id_preserved"],
        "blocked_wire": b["wire"],
        "blocked_dropped": b["dropped"],
        "blocked_billable": b["billable"],
        "unpaid_c": run["unpaid"]["a_to_c"],
        "unpaid_b": run["unpaid"]["a_to_b"],
        "paid_c": run["paid"]["a_to_c"],
        "pause_c": p["a_to_c"],
        "pause_b": p["a_to_b"],
        "resume_c": run["resume"]["a_to_c"],
    }

print()
print(f"{'run':>4} {'pause_ms':>9} {'link':>5} {'resume':>7} "
      f"{'blocked wire':>13} {'dropped':>9} {'billable':>9}")
for i, run in enumerate(runs, 1):
    r = row(run)
    print(f"{i:>4} {r['pause_ms']:>9} {str(r['link_ok']):>5} "
          f"{str(r['resume_link_ok']):>7} {r['blocked_wire']:>13} "
          f"{r['blocked_dropped']:>9} {r['blocked_billable']:>9}")

def rng(key):
    values = [row(r)[key] for r in runs]
    return min(values), max(values), statistics.median(values)

print()
print(f"pause command+checks : {rng('pause_ms')} ms")
print("link preserved       :", [row(r)["link_ok"] for r in runs])
print("resume link preserved:", [row(r)["resume_link_ok"] for r in runs])
print("blocked billable     :", [row(r)["blocked_billable"] for r in runs])
print("blocked dropped      :", [row(r)["blocked_dropped"] for r in runs])
print("flow                 :",
      [(row(r)["unpaid_c"], row(r)["paid_c"], row(r)["pause_c"], row(r)["resume_c"])
       for r in runs])
(out / "summary.json").write_text(json.dumps(runs, indent=2) + "\n")
print(f"\nraw logs and summary.json: {out}")
PY
