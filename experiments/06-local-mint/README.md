# 06 — Local mint and the receiver journal

**Question:** can a link session keep being paid while the mint is stopped, and
what happens after the keyset's `final_expiry`?

**Status:** not started. Phase 3. Runs **Exp F** and **Exp G**.

## Topology

```
seller (fipsd + tollgate-fips + journal)  <-- link -->  buyer (fipsd)
        |
   local test mint (Cashu, test unit)
```

No mainnet funds. Test mint only.

## What is being tested

- **Offline spentness.** The seller accepts a proof it has not checked with the
  mint, records the nullifier durably before granting credit, and refuses a
  replay after a restart.
- **Payment lane survival.** Killing the mint process must not stop an
  established session from renewing from the journal.
- **Exposure cap.** The face value of unsettled tokens never exceeds the cap.
- **Keyset expiry.** After `final_expiry` the mint may delete nullifiers
  (NUT-02). The seller must have rejected proofs that would expire inside the
  settlement window, and must not treat `final_expiry` as a session clock.

## Steps — Exp F

1. Start the mint, fund the buyer with test ecash, open a session.
2. Kill the mint process.
3. Continue traffic, exhaust, renew from the buyer's remaining proofs.
4. Record how long the session continues and what the seller does when it
   cannot settle.
5. Restart the seller. Replay a proof already in the journal. Confirm refusal.
6. Restart the mint. Confirm settlement of the backlog.

## Steps — Exp G

1. Start a mint with a short keyset expiry.
2. Hold proofs past `final_expiry`.
3. Try to spend and to settle. Record whether the mint drops nullifiers,
   refuses, or accepts.
4. Confirm the seller's admission predicate rejected proofs that would expire
   before `now + settlement_window`.

## Pass criteria

- [ ] Session survives the mint being stopped, for the stated window.
- [ ] No double spend accepted after a receiver restart.
- [ ] Exposure never exceeds the cap.
- [ ] `valid_until <= final_expiry − settlement_window` is enforced, with a
      test that would fail without it.

## Result files

`../../results/F-<date>.md`, `../../results/G-<date>.md`
