#!/bin/sh
# Build and run the nft netdev frame-gate correctness test.
#
# Usage: harness/ethernet-lab/run-frame-gate.sh [frames]
#
# Requires docker. The container gets NET_ADMIN (veth, nft) and NET_RAW
# (AF_PACKET). It does not need the host network.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FRAMES=${1:-200}
IMAGE=low-layer-tollgate-frame-gate

docker build -q -t "$IMAGE" "$HERE"
exec docker run --rm \
  --cap-add NET_ADMIN --cap-add NET_RAW \
  --network none \
  "$IMAGE" "$FRAMES"
