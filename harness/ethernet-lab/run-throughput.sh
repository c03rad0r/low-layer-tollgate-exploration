#!/bin/sh
# Build and run the frame-gate throughput benchmark.
#
# Usage: harness/ethernet-lab/run-throughput.sh [rates] [seconds]
#   rates    comma-separated pps targets (default 1000,10000,100000)
#   seconds  window per case (default 2)
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RATES=${1:-1000,10000,100000}
SECONDS=${2:-2}
IMAGE=low-layer-tollgate-frame-bench

docker build -q -f "$HERE/Dockerfile.bench" -t "$IMAGE" "$HERE"
exec docker run --rm \
  --cap-add NET_ADMIN --cap-add NET_RAW \
  --network none \
  "$IMAGE" "$RATES" "$SECONDS"
