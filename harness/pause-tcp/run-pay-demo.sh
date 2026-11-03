#!/usr/bin/env bash
# Capstone over TCP: unpaid -> paid -> pause -> renew on an A-B-C chain.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
COMPOSE="$HERE/docker-compose.yaml"

docker compose -f "$COMPOSE" down -v --remove-orphans >/dev/null 2>&1 || true
docker compose -f "$COMPOSE" up -d --remove-orphans
PAUSE_A=lt-pause-tcp-a PAUSE_B=lt-pause-tcp-b PAUSE_C=lt-pause-tcp-c \
  PYTHONPATH="$ROOT/sidecar" python3 "$ROOT/harness/pause/pay_demo.py"
