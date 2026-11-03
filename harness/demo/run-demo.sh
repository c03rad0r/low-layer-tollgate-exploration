#!/usr/bin/env bash
# Phase 1 demo: pay -> admit -> exhaust -> cut -> re-pay -> re-admit.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
DOWN=0
[ "${1:-}" = "--down" ] && DOWN=1

cleanup() {
  if [ "$DOWN" = 1 ]; then
    docker compose -f "$ROOT/harness/exp-c/docker-compose.yaml" \
      down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# Start from a clean ACL and link state. Reusing containers after repeated
# deny/allow flapping can leave a handshake stuck.
docker compose -f "$ROOT/harness/exp-c/docker-compose.yaml" \
  down -v --remove-orphans >/dev/null 2>&1 || true

PYTHONPATH="$ROOT/sidecar" python3 "$HERE/demo.py"
