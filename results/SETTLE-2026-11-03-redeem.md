# Result: SETTLE — redeem a P2PK token and close the money loop

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** settlement — verify → accept → redeem → settle → replay
- **Node(s):** local T14; Nutshell mint `lt-mint`
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **FIPS version / rev:** n/a
- **TollGate commit:** n/a
- **Repo commit:** settlement commit
- **Status:** pass

## Question

`PaymentGate.accept` reserves a journal row and takes exposure before the mint
confirms anything. Can the seller then redeem the P2PK token, close the
journal, release the exposure, and refuse a replay?

## Setup

```sh
harness/mint/run-settle-demo.sh
```

1. Mint a 50 sat P2PK+DLEQ token locked to the seller key
   `025dd0ec…9dff`.
2. Verify it offline against cached keys.
3. `PaymentGate.accept` each proof: journal RESERVED, exposure outstanding.
4. Redeem with the seller nsec inside the Nutshell image (the Cashu library
   signs each input's P2PK secret).
5. `SettlementWorker.settle`: journal SETTLED, exposure released.
6. Replay the token through the gate.
7. NUT-07 `checkstate` on the original inputs.

The seller nsec is a test identity; no real funds.

## Raw output

```json
{
  "verify_ok": true,
  "proofs": 3,
  "journal_after_accept": ["RESERVED", "RESERVED", "RESERVED"],
  "exposure_before_msat": "50000",
  "redemption": [{"ok": true, "balance": "343 sat", "unit": "sat"}],
  "vault_pending_before": 3,
  "vault_pending_after": 0,
  "settled": 3,
  "settled_tokens": 1,
  "failed": 0,
  "journal_after_settle": ["SETTLED", "SETTLED", "SETTLED"],
  "exposure_after_msat": "0",
  "replay_after_settle": "AlreadySettled",
  "nut07": {"Ys": 3, "states": ["SPENT", "SPENT", "SPENT"], "all_spent": true}
}
```

(The wallet balance is cumulative across lab runs; it is test ecash.)

## Measurements

| Step | Result |
|---|---|
| Offline verify | pass (3 proofs) |
| Journal after accept | RESERVED ×3 |
| Exposure after accept | **50,000 msat** |
| Vault rows before recovery | 3 (token persisted before the journal row) |
| Vault rows after recovery | **0** |
| Redemption | pass; mint received 49 sat net of the 1 sat input fee |
| Journal after settle | **SETTLED ×3** |
| Exposure after settle | **0** |
| Replay after settle | **AlreadySettled** |
| NUT-07 states | **SPENT ×3** |
| Settlement errors | none |

## Interpretation

1. **The money loop closes.** A real P2PK token is verified, accepted, redeemed
   at the mint, and the journal/exposure reflect the truth. Before this step the
   seller had a promise; after it, the seller has the value.
2. **Replay is refused after settlement.** The same token through the gate
   returns `AlreadySettled`. The journal is authoritative locally; the mint's
   SPENT state is the cross-check.
3. **Exposure release is exact.** 50,000 msat before, 0 after, no rounding.
4. **Recovery does not need the in-memory receipts.** The demo closes all three
   databases after acceptance, then reopens and settles purely from the token
   vault (`vault_pending 3 → 0`). The journal, exposure and replay checks all
   still pass, so the accept→settle crash window is closed.
5. **The redeemer belongs outside the sidecar.** It needs the `cashu` library
   and the seller's key; keeping it behind a `Redeemer` protocol keeps the gate
   dependency-free and lets a production seller choose its own redemption
   client.
6. **Input fees are real.** 50 sat in, 49 sat received: `input_fee_ppk=100`.
   Batching tokens into one swap would reduce this, which is the next
   optimisation.

## Caveats

- One token, one run, `FakeWallet`.
- The crash is simulated by closing the databases, not by killing a process.
  The redeem→settle window inside the drain is still untested.
- The redeemer runs in the Nutshell image as lab code, not in the seller.
- No batching and no background settlement worker.

## Follow-ups

- [ ] Batch several tokens into one swap to amortise input fees.
- [ ] Background worker that drains `pending()` with bounded retries.
- [ ] Record the redemption result before settling, to close the crash window.
- [ ] Reconcile a real double spend (same token to two sellers).

## Artefacts

- `sidecar/tollgate_fips/settlement.py`
- `sidecar/tests/test_settlement.py`
- `harness/mint/settle_demo.py`, `run-settle-demo.sh`
- `docs/0014-settlement.md`
