#!/bin/sh
# FrameGate module against real nftables (inside the E4 image).
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
IMAGE=low-layer-tollgate-token-bucket

docker build -q -f "$HERE/Dockerfile.ebpf" -t "$IMAGE" "$HERE" >/dev/null
exec docker run --rm \
  --cap-add NET_ADMIN --cap-add NET_RAW \
  --network none \
  --entrypoint python3 \
  -v "$ROOT/sidecar:/sidecar:ro" \
  -v "$HERE:/lab:ro" \
  -e PYTHONPATH=/sidecar:/lab \
  "$IMAGE" /lab/frame-gate-demo.py
