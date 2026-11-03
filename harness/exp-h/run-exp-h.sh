#!/usr/bin/env bash
# Exp H: deny the current parent and see whether the child re-parents.
#
# Usage:
#   harness/exp-h/run-exp-h.sh            # leave containers up
#   harness/exp-h/run-exp-h.sh --down     # tear down afterwards
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

echo "=== Exp H: three-node triangle, parent deny ==="
docker compose -f "$COMPOSE" up -d --remove-orphans

ARGS=()
for arg in "$@"; do
  [ "$arg" = "--down" ] || ARGS+=("$arg")
done
PYTHONPATH="$ROOT/sidecar" python3 "$HERE/exp_h.py" "${ARGS[@]}"
