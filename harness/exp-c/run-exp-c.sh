#!/usr/bin/env bash
# Exp C: bring up two FIPS nodes, cut the link, measure re-admit.
#
# Usage:
#   harness/exp-c/run-exp-c.sh            # leave containers up
#   harness/exp-c/run-exp-c.sh --down     # tear down afterwards
#
# Requires fips-test:latest built from the pinned FIPS tree:
#   cd <fips> && ./testing/scripts/build.sh
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
COMPOSE="$HERE/docker-compose.yaml"
DOWN=0
[ "${1:-}" = "--down" ] && DOWN=1

if ! docker image inspect fips-test:latest >/dev/null 2>&1; then
  echo "error: fips-test:latest not found" >&2
  echo "build it from the pinned FIPS tree: ./testing/scripts/build.sh" >&2
  exit 2
fi

cleanup() {
  if [ "$DOWN" = 1 ]; then
    docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "=== Exp C: two-node FIPS lab ==="
docker compose -f "$COMPOSE" up -d --remove-orphans

ARGS=()
for arg in "$@"; do
  [ "$arg" = "--down" ] || ARGS+=("$arg")
done
PYTHONPATH="$ROOT/sidecar" python3 "$HERE/exp_c.py" "${ARGS[@]}"
