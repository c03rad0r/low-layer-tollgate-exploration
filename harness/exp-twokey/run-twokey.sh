#!/usr/bin/env bash
# E-TWOKEY: one token, two acceptors, shared key vs different key.
set -euo pipefail
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK=${1:-/tmp/opencode/twokey-run-$(date +%s)}
PUB=${SELLER_PUBKEY:?33-byte compressed seller P2PK public key required}
NSEC=${SELLER_NSEC:?hex secp256k1 seller private key required for redemption}
OTHER=02aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
MINT=http://lt-mint:3338
rm -rf "$WORK"; mkdir -p "$WORK"
"$ROOT/harness/mint/run-mint.sh" >/dev/null
"$ROOT/harness/mint/mint-token.sh" 50 "$PUB" "$WORK/token.txt" >/dev/null
run() {
  docker run --rm --network lt-mint-net -e PYTHONPATH=/app:/sidecar:/mint \
    -v "$WORK:/data" -v "$ROOT/harness/exp-twokey:/exp:ro" \
    -v "$ROOT/harness/mint:/mint:ro" -v "$ROOT/sidecar:/sidecar:ro" \
    cashubtc/nutshell:latest python3 /exp/twokey.py "$@"
}
echo "=== fetch (online) ==="
run fetch --token /data/token.txt --keys /data/keys.json \
  --seller-pubkey "$PUB" --mint "$MINT"
echo "=== stop mint ==="
docker stop lt-mint >/dev/null
echo "=== accept (mint down) ==="
run accept --token /data/token.txt --keys /data/keys.json \
  --seller-pubkey "$PUB" --mint "$MINT"
echo "=== start mint ==="
docker start lt-mint >/dev/null; sleep 3
echo "=== redeem from both ==="
run redeem --token /data/token.txt --keys /data/keys.json \
  --seller-pubkey "$PUB" --seller-nsec "$NSEC" --mint "$MINT"
echo "=== diffkey ==="
run diffkey --token /data/token.txt --keys /data/keys.json \
  --seller-pubkey "$PUB" --other-pubkey "$OTHER" --mint "$MINT"
echo "=== sync ==="
run sync --token /data/token.txt --keys /data/keys.json \
  --seller-pubkey "$PUB" --mint "$MINT"
