# 0014 — Settlement: redeem, then close the journal and exposure

Status: implemented in `sidecar/tollgate_fips/settlement.py`; 6 unit tests and
an end-to-end settle demo (`results/SETTLE-2026-11-03-redeem.md`).

## The gap

`PaymentGate.accept` is optimistic. It writes a RESERVED journal row and takes
exposure before the mint confirms the value. Until the seller actually spends
the token at the mint, two things are true:

- the journal says "reserved", not "paid";
- the exposure cap stays consumed, so the payer cannot buy more.

`settle()` on the journal is a local state change. This module is the step that
makes it true at the mint.

## Flow

```text
verify (DLEQ/P2PK)            -> PaymentGate.accept
  journal RESERVED, exposure outstanding
redeem the token at the mint  -> inputs SPENT, seller receives fresh proofs
  journal SETTLED, exposure released
```

If redemption fails because the token is already spent, the caller calls
`reconcile_spent`, which marks the journal SPENT and releases the exposure. A
double spend is then refused forever and the payer's cap is free again.

## Why redemption, not just NUT-07

`/v1/checkstate` tells you whether an input is UNSPENT, PENDING or SPENT. It
does not transfer the value. Checking state and then releasing exposure would
leave the seller holding a token it never redeemed, exposed to the mint
deleting the keyset (Exp G) or the payer spending it elsewhere. Redemption is
the settlement.

## P2PK signalling

The seller's key is the lock target (`docs/0003`). The redeemer sets the
wallet's private key to the seller nsec and receives the token; the Cashu
library signs each input's secret because the lock names that key. In the lab
this ran inside the Nutshell image with the `cashu` library, so the sidecar
itself still has no Cashu dependency.

## API

```python
from tollgate_fips.settlement import SettlementWorker

worker = SettlementWorker(journal, exposure, redeemer)
worker.settle(receipts, token_string)   # redeem + SETTLED + release
worker.reconcile_spent(receipts)        # SPENT + release
worker.pending()                        # journal rows awaiting settlement
```

`redeemer.redeem(token)` returns `{"ok": bool, ...}`; a failure raises
`SettlementError` and leaves every row RESERVED and the exposure intact.

Settlement is idempotent: an already-SETTLED row is counted in
`already_settled`, not raised, so a retry after a crash does not fail a payment.

## Limits

- **One token at a time.** The caller passes the receipts the token backs.
- **Batching.** `settle_vault_batch(vault, batch_size)` redeems up to N tokens
  in one swap (`wallet.redeem(all_proofs)`), which saves the per-swap fee
  rounding. BATCH result: four 10 sat tokens, one swap, 1 sat instead of ~4.
- **Crash between redeem and settle.** The mint has the value, the journal still
  says RESERVED. Recovery must not re-credit. `recover_stale_reservations`
  remains the conservative fallback; a production worker should record the
  redemption result before settling.
- **Crash between accept and settle is covered by the vault.** The bearer token
  is written before the journal row commits (`TokenVault`), so a recovery worker
  can drain `vault.pending()` with `settle_vault()`. The demo closes all
  databases after acceptance and settles from the vault alone.
- **Draining.** `SettlementDaemon` polls the vault, calls `settle_vault_batch`,
  and backs off on refusal (`docs/0016-drain.md`).
- **The redeemer is lab code.** It runs in the Nutshell image, not in the seller.

## Tests

`sidecar/tests/test_settlement.py`: settle closes all rows and the exposure;
a failed redemption leaves everything reserved; a retry is idempotent;
`reconcile_spent` marks SPENT and releases; an empty receipt list is refused;
`pending()` lists reserved rows.
