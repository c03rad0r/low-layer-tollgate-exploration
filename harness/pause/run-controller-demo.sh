#!/usr/bin/env bash
# Controller-driven capstone: the seller loop pauses/resumes from session state.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
COMPOSE="$HERE/docker-compose.yaml"

docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$COMPOSE" up -d --remove-orphans
PYTHONPATH="$ROOT/sidecar" python3 "$HERE/controller_demo.py"
