#!/usr/bin/env bash
# Exp A2: runtime admission (patch a) vs the 1 s ACL-file tick.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
COMPOSE="$HERE/docker-compose.yaml"

docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$COMPOSE" up -d --remove-orphans
PYTHONPATH="$ROOT/sidecar" python3 "$HERE/admission.py"
