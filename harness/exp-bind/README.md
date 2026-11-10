# E-BIND harness

A two-payer FIPS application-replay lab. The seller maps a UDP packet's FIPS
IPv6 source to the authenticated npub from `fipsctl show peers` and applies a
used-token rule before granting credit.

## Inputs

- Real lab seeds in `configs/*.yaml` (`nsec: "REPLACE_WITH_HEX_SEED"` upstream).
- Two **test-only** Cashu tokens as `token1.txt` and `token2.txt` in this
  directory. Do not commit tokens; they are intentionally ignored by git.
- Docker with `fips-test:latest`.

For example, with the test mint already running and a seller's compressed
P2PK public key:

```sh
harness/mint/mint-token.sh 5 "$SELLER_PUBKEY" harness/exp-bind/token1.txt
harness/mint/mint-token.sh 10 "$SELLER_PUBKEY" harness/exp-bind/token2.txt
mkdir -p /tmp/opencode/bind-out
```

## Run

```sh
docker compose -f harness/exp-bind/docker-compose.yaml up -d --remove-orphans
PYTHONPATH=./sidecar python3 harness/exp-bind/bind.py
```

The JSON report is in `/tmp/opencode/bind-out/server-output.json`. The runner
expects the first five PAY messages to be delivered; no mint connection is used
by the listener in this arm.

`harness/exp-twokey/run-twokey.sh` takes an optional fresh work directory and
requires `SELLER_PUBKEY`/`SELLER_NSEC` for redemption. The analogous
`exp-expiry/run-expiry.sh` and `exp-outage/run-outage.sh` additionally require
`TOKEN_SRC` pointing at a pre-minted test P2PK token, and use
`/tmp/opencode/<experiment>-run-<timestamp>` per run.
