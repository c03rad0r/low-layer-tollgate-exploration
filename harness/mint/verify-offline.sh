#!/usr/bin/env bash
# Verify a token offline against cached keyset keys.
#
# Usage:
#   harness/mint/verify-offline.sh <token_file> <keys_file> <seller_pubkey> [mint_url]
#
# Run `verify_token.py` once online first (with --mint) to create keys_file.
set -euo pipefail

TOKEN=${1:?usage: verify-offline.sh <token> <keys.json> <seller_pubkey> [mint_url]}
KEYS=${2:?keys file required}
PUBKEY=${3:?seller compressed pubkey required}
MINT=${4:-http://lt-mint:3338}
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TOKEN_DIR=$(CDPATH= cd -- "$(dirname -- "$TOKEN")" && pwd)
TOKEN_BASE=$(basename "$TOKEN")
KEYS_DIR=$(CDPATH= cd -- "$(dirname -- "$KEYS")" && pwd)
KEYS_BASE=$(basename "$KEYS")

docker run --rm -e PYTHONPATH=/app \
  -v "${TOKEN_DIR}:/data/token:ro" \
  -v "${KEYS_DIR}:/data/keys:ro" \
  -v "${HERE}:/mint:ro" \
  cashubtc/nutshell:latest \
  python3 /mint/verify_token.py "/data/token/${TOKEN_BASE}" \
    --keys-file "/data/keys/${KEYS_BASE}" \
    --seller-pubkey "$PUBKEY" --mint "$MINT" --offline
