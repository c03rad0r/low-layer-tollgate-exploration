# 0018 — Treasury plane, not gate path

Status: decision note. No experiment is required for the decision; the
supporting measurements are in the settlement results. Exp J (cross-mint
time-to-admit) remains open as a buyer-side UX number.

## Decision

**Cross-mint swaps and treasury rebalancing are not part of the gate path.**

The gate accepts a payment in one advertised `(mint, unit, keyset)` at a time
and settles it against that mint. Moving value between mints is a **treasury**
operation: asynchronous, off the session's critical path, and invisible to the
session state machine.

A Granola-style swap is a useful treasury tool. It is not an admission
primitive, and the protocol must not make a session's liveness depend on one.

## The two planes

| | Gate plane | Treasury plane |
|---|---|---|
| Question | may this peer forward now, and for how many bytes? | where should the seller's value sit? |
| Unit | bytes per millisat, one `(mint, unit, keyset)` | value across mints/currencies |
| Timing | synchronous, per tick | asynchronous, minutes/hours |
| Failure | pause or evict a session | retry, rebalance later |
| State | session, journal, exposure | treasury balances, swap history |
| Counterparty | payer and mint | swap provider / counterparty |

The only shared object is the ecash itself. The treasury never writes the
journal, never credits a session and never changes a verdict.

## Why a swap cannot be an admission step

1. **Liveness.** A swap needs a counterparty. If admission waits for one, a
   thin market, a relay outage or a rejected quote becomes a payment outage.
   The gate already has a hard enough dependency: one mint it chose.
2. **Atomicity.** A cross-mint swap is multi-step (lock, quote, swap, redeem).
   A failure halfway leaves value in flight. The gate's contract is binary:
   verified and reserved, or rejected. A half-swapped payment has no honest
   session state.
3. **Latency.** Admission is measured in hundreds of milliseconds to a few
   seconds (Exp C, A2). A swap adds a network round trip to another party, and
   possibly a confirmation wait, before the first byte is authorised.
4. **Accounting.** Metering is in bytes per millisat inside one unit. A swap
   introduces a second price, a spread and rounding. The session would need to
   know which rate applied to which byte — a dispute the protocol cannot settle
   after the fact.
5. **Exposure.** The exposure cap bounds unsettled value per payer, mint and
   unit (`docs/0010`). A swap does not remove cross-seller double spend; it
   changes which mint carries it. The cap still has to do its job.
6. **Privacy and coupling.** A swap provider sees payer and seller flow. Making
   it mandatory puts a third party in every session and gives it a timing signal
   the protocol otherwise avoids.

## What the gate does instead

- A seller advertises the mints and units it accepts (P1's endpoint
  advertisement is the natural place).
- The buyer pays in one of them. If the buyer holds a different mint, the
  **buyer** swaps first, then pays; that is a pre-payment step, not an
  admission step.
- The seller credits, meters and pauses against that one mint. Settlement is
  per mint (`docs/0014`), batched (`results/BATCH-2026-11-03.md`), retried with
  backoff and dead-lettered (`docs/0016`).
- After `SETTLED`, the value is the seller's. Consolidating it across mints is
  treasury work.

This keeps one rule: **the gate sees one voucher and one mint.** Anything more
complex is composed before or after it.

## Where the treasury plane fits

```text
payer --token(mint X)--> gate --> journal SETTLED --> seller balance at X
                                                         |
                                                         |  asynchronous
                                                         v
                                              treasury / Granola swap
                                                         |
                                                         v
                                                balance at mint Y
```

The treasury can move value for liquidity, fees, or operator preference. It
cannot move a session out of `grace`, and its failure cannot evict a peer.

## If the assumption changes

Suppose a swap becomes atomic and fast enough to sit inside a payment. Even
then, the correct shape is an **accepted payment method** behind the existing
payment gate: the gate verifies one result and records one nullifier/exposure
entry. It still should not meter, pause or evict on swap state. That preserves
the invariant above and keeps the failure domain unchanged.

## Exp J

Exp J was "cross-mint time-to-admit". Reframed by this decision:

- measure the buyer's **time-to-pay** when a swap is required (pre-payment);
- compare it with the same buyer holding the seller's mint (direct payment);
- do **not** add a swap to the admission path to measure it.

The number is useful for UX and for telling a buyer what to expect. It is not a
gate parameter.

## Evidence

| Claim | Source |
|---|---|
| Settlement is per mint/keyset and batched | `results/BATCH-2026-11-03.md` |
| A failed mint is retried, then parked | `results/DEADLETTER-2026-11-03.md` |
| Settlement never blocks admission | `docs/0014`, `docs/0016` |
| Exposure is per payer/mint/unit | `docs/0010`, `results/DEADLETTER-2026-11-03.md` |
| Offline verification is per mint keyset | `results/F-2026-11-03-offline-verify.md` |

## Consequences for the spec

- P1 advertises accepted mints/units; it does not advertise a swap provider.
- P3's unit is the session's `(mint, unit)`, not a cross-mint basket.
- P4's states are independent of treasury state.
- A future "payment methods" TIP may describe a swap as a buyer-side method,
  but the gate interface and the four states stay as they are.
