#!/usr/bin/env bash
# Batch settlement: four tokens, one swap.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK=${BATCH_WORK:-/tmp/opencode/batch}
TOKENS=${BATCH_TOKENS:-4}
SELLER_PUBKEY=REPLACE_WITH_HEX_SEEDff
SELLER_NSEC=REPLACE_WITH_HEX_SEED
SELLER_NPUB=npub1thgwcxk5x45r9vusqzksmxnewfkgzhrdf4dlnc75ky96g6swnhlszjzgrw

mkdir -p "$WORK"
"$ROOT/harness/mint/run-mint.sh" >/dev/null
FILES=()
for i in $(seq 1 "$TOKENS"); do
  timeout 120 "$ROOT/harness/mint/mint-token.sh" 10 "$SELLER_PUBKEY" "$WORK/token$i.txt" >/dev/null
  FILES+=("/data/token$i.txt")
done

docker run --rm --network lt-mint-net -e PYTHONPATH=/app:/sidecar:/mint \
  -v "$WORK:/data" \
  -v "$ROOT/sidecar:/sidecar:ro" \
  -v "$HERE:/mint:ro" \
  cashubtc/nutshell:latest \
  python3 /mint/batch_redeem.py "${FILES[@]}" \
    --keys-file /data/keys.json \
    --seller-pubkey "$SELLER_PUBKEY" \
    --seller-npub "$SELLER_NPUB" \
    --seller-nsec "$SELLER_NSEC" \
    --mint http://lt-mint:3338 \
    --db-dir "/data/settle-batch-$(date +%s)" \
    --wallet-dir /data/batch-wallet
