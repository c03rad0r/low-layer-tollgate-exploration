# Local Cashu test mint

A real Nutshell mint (`cashubtc/nutshell:0.21.0`) with the `FakeWallet`
Lightning backend. No real funds, no Lightning node, no mainnet. The mint
supports NUT-11 P2PK, NUT-12 DLEQ and NUT-07; it is the target for Exp F/G.

## Start

```sh
harness/mint/run-mint.sh
```

- network `lt-mint-net`
- container `lt-mint`, published at `127.0.0.1:3338`
- data volume `lt-mint-data` (`MINT_DATABASE=/data/mint`)
- wallet volume `lt-wallet-data` (`CASHU_DIR=/data`)
- fixed test private key; not a secret, not for production

The in-network URL for wallets is `http://lt-mint:3338`; the token records that
URL, so verify it with `--mint http://lt-mint:3338`.

## Mint a P2PK token

```sh
harness/mint/mint-token.sh 50 <seller-compressed-pubkey> /tmp/opencode/token.txt
```

The pubkey must be the **33-byte compressed** form (`02`/`03` + 32 bytes). An
x-only npub is not enough for NUT-11: Nutshell rejects it as a malformed
compressed public key. The seller derives the compressed key from its FIPS
nsec. For the Exp C/H test seller this is:

```
REPLACE_WITH_HEX_SEEDa4
```

The script mints via a FakeWallet invoice (auto-paid), then `send -d -l
P2PK:<pubkey>` and writes the token. It prints `cashuB...` test ecash; treat it
as a bearer instrument even though it is worthless.

## Verify

First run online to cache the keyset public keys:

```sh
docker run --rm -e PYTHONPATH=/app --network lt-mint-net \
  -v /tmp/opencode:/data -v "$PWD/harness/mint:/mint:ro" \
  cashubtc/nutshell:latest \
  python3 /mint/verify_token.py /data/token.txt \
    --keys-file /data/keys.json \
    --seller-pubkey REPLACE_WITH_HEX_SEEDa4 \
    --mint http://lt-mint:3338
```

Then with the mint stopped:

```sh
docker stop lt-mint
harness/mint/verify-offline.sh /tmp/opencode/token.txt /tmp/opencode/keys.json \
  REPLACE_WITH_HEX_SEEDa4
docker start lt-mint
```

The verifier checks DLEQ against the cached keyset key, the P2PK lock, the
locktime window and the amount sum. It does **not** check spentness; that is the
journal's job. `final_expiry` for the default keyset is null; Exp G needs a
rotated keyset with a short expiry (management RPC).

## PaymentGate and replay

`gate_token.py` feeds the verified proofs into `PaymentGate`, the journal and the
exposure ledger, reopens the databases to simulate a restart, replays, settles
and replays again:

```sh
docker stop lt-mint
docker run --rm -e PYTHONPATH=/app:/sidecar:/mint \
  -v /tmp/opencode:/data -v "$PWD/sidecar:/sidecar:ro" \
  -v "$PWD/harness/mint:/mint:ro" cashubtc/nutshell:latest \
  python3 /mint/gate_token.py /data/token.txt --keys-file /data/keys.json \
    --seller-pubkey REPLACE_WITH_HEX_SEEDa4 \
    --seller-npub <npub> --mint http://lt-mint:3338 --db-dir /data/f-gate
docker start lt-mint
```

Expected: 3 proofs accepted, exposure 50,000 msat, replay
`ReservationInFlight`, settle clears exposure, replay `AlreadySettled`.

## Exp G — short `final_expiry`

```sh
harness/mint/expiry.py
```

Pins `final_expiry` on the active keyset in the mint's SQLite store, checks the
receiver predicate, waits past expiry, and tries a spend. Nutshell 0.21.0 keeps
the keyset active and accepts the spend, so the seller predicate is the only
guard. The script restores `final_expiry = NULL`. Result:
`results/G-2026-11-03-final-expiry.md`.

## Settlement

```sh
harness/mint/run-settle-demo.sh
```

Verify → `PaymentGate.accept` (RESERVED, exposure) → redeem with the seller key
→ journal SETTLED + exposure 0 → replay refused → NUT-07 inputs SPENT. Result:
`results/SETTLE-2026-11-03-redeem.md`.

## Batch settlement

```sh
harness/mint/run-batch-demo.sh
BATCH_TOKENS=8 harness/mint/run-batch-demo.sh
```

Four 10 sat tokens, accepted into the vault, then one swap redeems all eight
inputs. Fee 1 sat versus ~4 for separate swaps. Result:
`results/BATCH-2026-11-03.md`.

## Stop / reset

```sh
docker stop lt-mint
docker rm -f lt-mint
docker volume rm lt-mint-data lt-wallet-data   # destroys test ecash
```

## Result

`results/F-2026-11-03-offline-verify.md`
