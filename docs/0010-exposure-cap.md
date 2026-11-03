# 0010 — Exposure cap

Status: Phase 3 core implemented in `sidecar/tollgate_fips/exposure.py`; 10
tests. Not yet wired to a verifier or a mint.

## The residual risk

The journal (`docs/0009`) prevents a replay at **one** receiver. It cannot see a
token given to two sellers: each journal sees the first acceptance and both
grant credit. No local record can close that without asking the mint.

The exposure cap bounds the loss:

> At most `cap_msat` of unsettled face value per
> `(payer_npub, mint_url, unit)`.

It is not a settlement guarantee. It is a limit on how much a seller is willing
to lend a payer before the mint answers.

## Key

```
(payer_npub, mint_url, unit)
```

- `payer_npub` is the proven FIPS identity from the link, bound into the
  payment preamble (`docs/0003`).
- `mint_url` and `unit` separate trust domains and denominations.
- `keyset_id` is deliberately **not** in the exposure key: the cap is about the
  payer's total unsettled value at a mint, across keysets.

## Ordering

On acceptance:

1. verify the proof (signature, P2PK to seller, DLEQ);
2. check `keyset_admissible(final_expiry, settlement_window)`;
3. **reserve exposure**;
4. **reserve the journal nullifier**;
5. grant credit.

Exposure is reserved before the journal row on purpose:

| Crash point | Result |
|---|---|
| after exposure reserve, before journal reserve | exposure overstates; the seller lends less until reconciled. Never a double spend. |
| after journal reserve, before credit | exposure and journal both reserved; conservative |
| after credit | normal |

The reverse order would let a crash leave the journal reserved but exposure
unaccounted, which understates the cap and is the dangerous direction.

On settlement: `journal.settle()` then `exposure.release()`.
On a detected double spend: `journal.mark_spent()` then `exposure.release()`.

Both releases are idempotent in the sense that the outstanding value clamps at
zero; a repeated release cannot create negative exposure.

## Cap policy

The cap is a seller policy, not a protocol constant. Inputs:

- the seller's per-payer loss tolerance;
- the settlement window (how long a proof can stay unsettled);
- the mint's trust tier (`docs/0003`): a local mint can use a much larger cap
  than a foreign mint, because spentness is local;
- the batch size: batching reduces NUT-02 input fees but increases exposure.

The spec should name the field and the ordering, not a universal number.
`Q4` in the checklist is still open.

## What it does not solve

- **Fraud by the mint.** A mint that signs a token and then refuses to settle is
  outside both the journal and the cap.
- **Cross-mint double spend.** A token cannot move between mints, so the key
  separates them; a payer can still overcommit at two mints. Each seller's cap
  applies independently.
- **Settlement failure.** A proof that is valid but never settles remains
  exposure until the operator writes it off. The journal's stale recovery is
  the hook for that reconciliation.

## API

```python
from tollgate_fips.exposure import ExposureKey, ExposureLedger

key = ExposureKey(payer_npub, mint_url, unit)
ledger.reserve(key, amount_msat, cap_msat)   # before journal.reserve
...
ledger.release(key, amount_msat)             # after settle or spend
ledger.outstanding(key)
```

`reserve()` is one `BEGIN IMMEDIATE` transaction: two concurrent payments
cannot both pass a cap that only one should. `release()` clamps at zero and
raises `UnknownExposure` if the key was never reserved.

## Tests

```
PYTHONPATH=sidecar python3 -m unittest discover -s sidecar/tests -v
```

Cap enforcement, zero cap, release/clamp, unknown key, key independence, exact
`Decimal` amounts, reopen persistence, and a second connection seeing the cap.

## Next

- A `PaymentGate` that calls verifier → exposure → journal in that order.
- A local test mint and a real NUT-11/NUT-07 path.
- Batch settlement and the exposure number for `Q4`.
