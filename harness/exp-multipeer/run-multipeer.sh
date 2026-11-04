#!/usr/bin/env bash
# Exp MULTIPEER: four-node star, per-peer block isolation.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
COMPOSE="$HERE/docker-compose.yaml"
DOWN=0
[ "${1:-}" = "--down" ] && DOWN=1

cleanup() {
  if [ "$DOWN" = 1 ]; then
    docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$COMPOSE" up -d --remove-orphans
PYTHONPATH="$ROOT/sidecar" python3 "$HERE/multipeer.py"
