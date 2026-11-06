#!/usr/bin/env bash
# Start or reuse the local Nutshell test mint (FakeWallet, no real funds).
set -euo pipefail

NAME=${MINT_NAME:-lt-mint}
NET=${MINT_NET:-lt-mint-net}
VOL=${MINT_VOLUME:-lt-mint-data}
PORT=${MINT_PORT:-3338}

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
docker volume create "$VOL" >/dev/null

if docker container inspect "$NAME" >/dev/null 2>&1; then
  docker start "$NAME" >/dev/null
else
  docker run -d --name "$NAME" --network "$NET" \
    -p "127.0.0.1:${PORT}:3338" \
    -e MINT_BACKEND_BOLT11_SAT=FakeWallet \
    -e MINT_LISTEN_HOST=0.0.0.0 \
    -e MINT_LISTEN_PORT=3338 \
    # Fixed test key for the local FakeWallet mint; holds no value.
    -e MINT_PRIVATE_KEY=0000000000000000000000000000000000000000000000000000000000000001 \
    -e MINT_DATABASE=/data/mint \
    -e MINT_INFO_NAME="TollGate test mint" \
    -e MINT_INFO_DESCRIPTION="Local FakeWallet test mint; no real funds" \
    -v "${VOL}:/data" \
    cashubtc/nutshell:latest python3 -m cashu.mint >/dev/null
fi

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/v1/info" >/dev/null 2>&1; then
    echo "mint ready: http://127.0.0.1:${PORT} (container ${NAME})"
    echo "in-network URL for wallets: http://${NAME}:3338"
    exit 0
  fi
  sleep 1
done

echo "error: mint did not become ready" >&2
docker logs "$NAME" 2>&1 | tail -30 >&2
exit 1
