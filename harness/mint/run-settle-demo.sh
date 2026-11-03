#!/usr/bin/env bash
# Verify -> accept -> redeem -> settle -> replay, with the mint running.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK=${SETTLE_WORK:-/tmp/opencode/settle}
SELLER_PUBKEY=REPLACE_WITH_HEX_SEEDff
SELLER_NSEC=REPLACE_WITH_HEX_SEED
SELLER_NPUB=npub1thgwcxk5x45r9vusqzksmxnewfkgzhrdf4dlnc75ky96g6swnhlszjzgrw

mkdir -p "$WORK"
DB="/data/settle-$(date +%s)"
"$ROOT/harness/mint/run-mint.sh" >/dev/null
"$ROOT/harness/mint/mint-token.sh" 50 "$SELLER_PUBKEY" "$WORK/token.txt" >/dev/null

docker run --rm --network lt-mint-net -e PYTHONPATH=/app:/sidecar:/mint \
  -v "$WORK:/data" \
  -v "$ROOT/sidecar:/sidecar:ro" \
  -v "$HERE:/mint:ro" \
  cashubtc/nutshell:latest \
  python3 /mint/settle_demo.py /data/token.txt \
    --keys-file /data/keys.json \
    --seller-pubkey "$SELLER_PUBKEY" \
    --seller-npub "$SELLER_NPUB" \
    --seller-nsec "$SELLER_NSEC" \
    --mint http://lt-mint:3338 \
    --db-dir "$DB" \
    --wallet-dir /data/settler-wallet
