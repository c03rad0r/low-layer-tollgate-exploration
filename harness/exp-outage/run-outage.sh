#!/usr/bin/env bash
set -euo pipefail
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK=/tmp/opencode/outage-run-$(date +%s)
PUB=${SELLER_PUBKEY:?33-byte compressed seller P2PK public key required}
NSEC=${SELLER_NSEC:?hex secp256k1 seller private key required for redemption}
MINT=http://lt-mint:3338
mkdir -p "$WORK"; cp "${TOKEN_SRC:?path to a pre-minted P2PK token}" "$WORK/token.txt"
"$ROOT/harness/mint/run-mint.sh" >/dev/null
docker stop lt-mint >/dev/null
docker run --rm -v lt-mint-data:/data cashubtc/nutshell:latest python3 -c \
 'import sqlite3; con=sqlite3.connect("/data/mint/mint.sqlite3"); con.execute("UPDATE keysets SET final_expiry=NULL"); con.commit()'
docker start lt-mint >/dev/null; sleep 3
run() {
 docker run --rm --network lt-mint-net -e PYTHONPATH=/app:/sidecar:/mint \
  -v "$WORK:/data" -v "$ROOT/harness/exp-outage:/exp:ro" \
  -v "$ROOT/harness/mint:/mint:ro" -v "$ROOT/sidecar:/sidecar:ro" \
  cashubtc/nutshell:latest python3 /exp/outage.py "$@"
}
echo '=== fetch keys ==='
docker run --rm --network lt-mint-net -e PYTHONPATH=/app -v "$WORK:/data" -v "$ROOT/harness/mint:/mint:ro" cashubtc/nutshell:latest \
 python3 /mint/verify_token.py /data/token.txt --keys-file /data/keys.json --seller-pubkey "$PUB" --mint "$MINT" >/dev/null
echo '=== stop mint ==='
docker stop lt-mint >/dev/null
echo '=== accept offline ==='
run accept /data/token.txt --keys-file /data/keys.json --seller-pubkey "$PUB" --db-dir /data/gate --mint "$MINT"
echo '=== outage 30s ==='
sleep 30
echo '=== start mint and settle ==='
docker start lt-mint >/dev/null; sleep 3
run settle /data/token.txt --keys-file /data/keys.json --seller-pubkey "$PUB" --seller-nsec "$NSEC" --db-dir /data/gate --mint "$MINT"
