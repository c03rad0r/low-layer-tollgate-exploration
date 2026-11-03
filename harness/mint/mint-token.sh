#!/usr/bin/env bash
# Mint test ecash and send a P2PK+DLEQ token to a seller pubkey.
#
# Usage:
#   harness/mint/mint-token.sh <amount_sat> <seller_compressed_pubkey> [out_file]
#
# The seller pubkey must be the 33-byte compressed form (02/03 + 32 bytes).
# An x-only npub is not enough for NUT-11; see results/F-2026-11-03-offline-verify.md.
set -euo pipefail

AMOUNT=${1:?usage: mint-token.sh <amount_sat> <seller_pubkey> [out_file]}
PUBKEY=${2:?seller compressed pubkey required}
OUT=${3:-/tmp/opencode/token.txt}
NAME=${MINT_NAME:-lt-mint}
NET=${MINT_NET:-lt-mint-net}
VOL=${WALLET_VOLUME:-lt-wallet-data}

case "$PUBKEY" in
  02*|03*) ;;
  *) echo "error: seller pubkey must start with 02 or 03 (compressed)" >&2; exit 2 ;;
esac
[ ${#PUBKEY} -eq 66 ] || { echo "error: seller pubkey must be 66 hex chars" >&2; exit 2; }

docker volume create "$VOL" >/dev/null
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

docker run --rm --network "$NET" -v "${VOL}:/data" -e CASHU_DIR=/data \
  cashubtc/nutshell:latest \
  python3 -m cashu.wallet --host "http://${NAME}:3338" -y invoice "$AMOUNT" \
  >"$LOG" 2>&1
if ! grep -q "Invoice paid" "$LOG"; then
  echo "error: FakeWallet invoice was not paid" >&2
  tail -20 "$LOG" >&2
  exit 1
fi

TOKEN=$(docker run --rm --network "$NET" -v "${VOL}:/data" -e CASHU_DIR=/data \
  cashubtc/nutshell:latest \
  python3 -m cashu.wallet --host "http://${NAME}:3338" -y \
  send -d -l "P2PK:${PUBKEY}" "$AMOUNT" 2>>"$LOG" | grep -m1 '^cashuB' || true)

if [ -z "$TOKEN" ]; then
  echo "error: no token produced" >&2
  tail -30 "$LOG" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
printf '%s\n' "$TOKEN" > "$OUT"
echo "token written to $OUT (${#TOKEN} chars, ${AMOUNT} sat, P2PK to ${PUBKEY})"
echo "this is test ecash, not real funds"
