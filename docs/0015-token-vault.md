# 0015 — The token vault (crash-safe acceptance)

Status: implemented in `sidecar/tollgate_fips/vault.py`; 6 unit tests, wired
into `PaymentGate.accept` and `SettlementWorker.settle_vault`; recovery demo in
`results/SETTLE-2026-11-03-redeem.md`.

## The window

`PaymentGate.accept` creates a RESERVED journal row and takes exposure before
the seller has redeemed the token. If the process dies before settlement, the
journal says RESERVED but the token — the only thing that can settle it — was
only in the caller's memory. Credit was granted for value the seller can no
longer recover.

## The fix

A `TokenVault` (SQLite, WAL + `synchronous=FULL`) stores the bearer token keyed
by the proof's nullifier tuple. Ordering in `accept`:

```text
verify
  -> reserve exposure
  -> vault.put(token)          <-- before the journal row
  -> journal.reserve(nullifier)
  -> grant credit
```

If `journal.reserve` refuses (a replay), the gate releases the exposure and
removes the vault row **only if this call created it**, so a replay can never
overwrite or delete the first payment's token.

The failure directions are asymmetric on purpose:

| Crash point | Result |
|---|---|
| after exposure, before vault | exposure overstates; no credit, no token |
| after vault, before journal | orphan token row; recoverable/refundable |
| after journal, before credit | reserved row plus token; recovery settles or refuses |
| after credit | normal |

## Recovery

```python
worker.settle_vault(vault)
```

groups pending rows by token, redeems each token once, then settles every
journal row it backs and releases the exposure. A failed redemption leaves the
rows pending and reports the error; a token the mint says is already spent goes
through `reconcile_spent` instead.

The recovery demo closes all three databases after acceptance, reopens them, and
settles from the vault alone: `vault_pending 3 → 0`, journal SETTLED ×3,
exposure 0, replay `AlreadySettled`, NUT-07 inputs SPENT.

## This database is money

It stores bearer tokens. Treat it like a wallet:

- file permissions and full-disk encryption are the operator's job;
- back it up with the same care as the mint balance;
- do not log token strings (the vault error path truncates them).

## Limits

- One row per proof, so the token string is duplicated per proof. A normal form
  (payments → receipts) is the next schema step.
- No expiry/GC policy for rows that never settle (a failed redemption forever).
- The redeem→settle window inside `settle_vault` is still untested: a crash
  after the mint accepts the swap but before the journal commits leaves a
  pending row whose token is already spent. That must reconcile as SPENT, not
  re-credit.
