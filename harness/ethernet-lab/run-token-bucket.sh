#!/bin/sh
# Exp E4: per-MAC token bucket, nft vs tc-police vs tc/BPF.
#
# Usage: harness/ethernet-lab/run-token-bucket.sh [repeats]
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPEATS=${1:-3}
IMAGE=low-layer-tollgate-token-bucket

docker build -q -f "$HERE/Dockerfile.ebpf" -t "$IMAGE" "$HERE"
exec docker run --rm \
  --cap-add NET_ADMIN --cap-add NET_RAW \
  --cap-add BPF --cap-add PERFMON --cap-add SYS_ADMIN \
  --network none \
  "$IMAGE" "$REPEATS"
