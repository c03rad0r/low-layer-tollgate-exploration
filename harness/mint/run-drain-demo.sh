#!/usr/bin/env bash
# Background drain: one token, accepted then settled by the daemon loop.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
WORK=${DRAIN_WORK:-/tmp/opencode/drain}
SELLER_PUBKEY=REPLACE_WITH_HEX_SEEDff
SELLER_NSEC=REPLACE_WITH_HEX_SEED
SELLER_NPUB=npub1thgwcxk5x45r9vusqzksmxnewfkgzhrdf4dlnc75ky96g6swnhlszjzgrw

mkdir -p "$WORK"
"$ROOT/harness/mint/run-mint.sh" >/dev/null
timeout 120 "$ROOT/harness/mint/mint-token.sh" 10 "$SELLER_PUBKEY" "$WORK/token.txt" >/dev/null

docker run --rm --network lt-mint-net -e PYTHONPATH=/app:/sidecar:/mint \
  -v "$WORK:/data" \
  -v "$ROOT/sidecar:/sidecar:ro" \
  -v "$HERE:/mint:ro" \
  cashubtc/nutshell:latest \
  python3 /mint/drain_demo.py /data/token.txt \
    --keys-file /data/keys.json \
    --seller-pubkey "$SELLER_PUBKEY" \
    --seller-npub "$SELLER_NPUB" \
    --seller-nsec "$SELLER_NSEC" \
    --mint http://lt-mint:3338 \
    --db-dir "/data/drain-$(date +%s)" \
    --wallet-dir /data/drain-wallet \
    --poll 1.0
