#!/usr/bin/env bash
set -euo pipefail
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK=/tmp/opencode/expiry-run-$(date +%s)
PUB=${SELLER_PUBKEY:?33-byte compressed seller P2PK public key required}
NSEC=${SELLER_NSEC:?hex secp256k1 seller private key required for redemption}
MINT=http://lt-mint:3338
rm -rf "$WORK"; mkdir -p "$WORK"
"$ROOT/harness/mint/run-mint.sh" >/dev/null
# Normalize the keyset first, then mint the token while the keyset is valid.
docker stop lt-mint >/dev/null
docker run --rm -v lt-mint-data:/data cashubtc/nutshell:latest python3 -c  'import sqlite3; con=sqlite3.connect("/data/mint/mint.sqlite3"); con.execute("UPDATE keysets SET final_expiry=NULL"); con.commit()'
docker start lt-mint >/dev/null; sleep 3
cp "${TOKEN_SRC:?path to a pre-minted P2PK token}" "$WORK/token.txt"

EXPIRY=$(( $(date +%s) + 90 ))
docker stop lt-mint >/dev/null
docker run --rm -v lt-mint-data:/data cashubtc/nutshell:latest python3 -c  'import sqlite3,sys; con=sqlite3.connect("/data/mint/mint.sqlite3"); cur=con.execute("UPDATE keysets SET final_expiry=?",(sys.argv[1],)); con.commit(); print(cur.fetchall())' "$EXPIRY"
docker start lt-mint >/dev/null; sleep 3
echo "set final_expiry=$EXPIRY ($(date +%s) now)"
run() {
 docker run --rm --network lt-mint-net -e PYTHONPATH=/app:/sidecar:/mint \
  -v "$WORK:/data" -v "$ROOT/harness/exp-expiry:/exp:ro" \
  -v "$ROOT/harness/mint:/mint:ro" -v "$ROOT/sidecar:/sidecar:ro" \
  cashubtc/nutshell:latest python3 /exp/expiry_accept.py "$@"
}
echo '=== window 3600s ==='
run /data/token.txt --keys-file /data/keys.json --seller-pubkey "$PUB" --window 3600 --db-dir /data/long --mint "$MINT"
echo '=== window 30s ==='
run /data/token.txt --keys-file /data/keys.json --seller-pubkey "$PUB" --window 30 --db-dir /data/short --mint "$MINT"
echo "=== wait $((EXPIRY-$(date +%s)+5))s to cross final_expiry ==="
sleep $((EXPIRY-$(date +%s)+5))
echo '=== after expiry: redeem at mint ==='
run /data/token.txt --keys-file /data/keys.json --seller-pubkey "$PUB" --seller-nsec "$NSEC" --window 30 --db-dir /data/after --mint "$MINT" --redeem
