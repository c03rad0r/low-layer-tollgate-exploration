# Result: OUTAGE — offline credit settles exactly on reconnect

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-OUTAGE (docs/0019, decision D3)
- **Mint:** Nutshell 0.21.0, `FakeWallet`, test ecash only
- **Status:** completed 30-second outage arm

## Question

After accepting real P2PK notes with the mint down, do the journal, token vault
and settlement path release exactly the reserved exposure when connectivity
returns?

## Setup

A real 10 sat P2PK+DLEQ token (two proofs) is cached and the mint keys fetched
online. The mint is stopped for 30 seconds. The seller accepts offline, persists
the bearer value and reserves 10,000 msat, then reconnects and settles from the
reopened databases. This is the primitive for a balloon that must grant credit
without constant mint access.

```sh
TOKEN_SRC=/tmp/opencode/token.txt \
  harness/exp-outage/run-outage.sh
```

## Raw output

### Accepted offline

```json
{
  "phase": "accept",
  "offline": true,
  "amount_sat": 10,
  "exposure_msat": "10000",
  "journal": ["RESERVED", "RESERVED"],
  "vault_pending": 2
}
```

### After 30 seconds offline, mint restarted and settled

```json
{
  "phase": "settle",
  "exposure_before_msat": "10000",
  "exposure_after_msat": "0",
  "settled": 2,
  "failed": 0,
  "redemptions": [{"ok": true, "balance": "9 sat"}],
  "journal": ["SETTLED", "SETTLED"],
  "vault_pending": 0,
  "replay": "AlreadySettled"
}
```

10 sat became 9 sat received after the input fee; exposure released exactly
10,000 msat to zero. A replay after settlement was refused as `AlreadySettled`.

## Interpretation

1. **The balloon does not need the mint to decide offline acceptance.** Cached
   keyset keys plus a valid P2PK lock enable verification before forwarding; it
   needs the mint later to turn that credit into settled value.
2. **Local persistence, not the mint, prevents replay at this receiver.** The
   two accepted proofs were present in both the reservation journal and token
   vault before settlement. Recovery used the reopened files, not live memory.
3. **Exposure accounting closes precisely.** Offline accepted value was visible
   during the outage, then released after redemption; there is no rounding or
   "free" residual.

## Decision for D3

Offline notes can be accepted with a capped exposure and settled opportunistically
on any later mint connection. The offline cap should represent the amount of
credit the operator could lose if settlement never happens or fails; it is not a
guarantee of conversion.

## Caveats and follow-ups

- This was 30 seconds, not 1/6/24/72 hours. It validates the mechanism, not a
  distribution of outage outcomes.
- One payer, one token, one keyset. No batch-size sweep or mint-side rotation.
- The adversarial arm (mint reports already-spent after offline credit) is covered
  by the shared-key behavior in `TWOKEY-2026-11-10-offline-shared-key.md`; an
  explicit dead-letter alarm measurement remains a follow-up.
- No real power-cut, host crash, or on-device flash timing in this run.

## Artefacts

- `harness/exp-outage/run-outage.sh`, `outage.py`.
- `results/SETTLE-2026-11-03-redeem.md`,
  `results/EXPIRY-2026-11-10-p2pk-settlement-window.md`.
