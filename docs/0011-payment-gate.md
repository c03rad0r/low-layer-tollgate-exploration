# 0011 — The payment gate: verifier → exposure → journal

Status: integration implemented in `sidecar/tollgate_fips/payment.py`; 8 tests
with a stub verifier. The real verifier (NUT-11/DLEQ/NUT-07) is not written.

## What it is

`PaymentGate.accept(proof, msg1_ephemeral)` is the one place that decides
whether a payment proof buys credit. It does not verify money itself and it does
not settle. It orders the three checks that must happen, and records the result
durably.

```
verify proof
  -> check keyset final_expiry
  -> reserve exposure
  -> reserve nullifier
  -> grant credit
```

## The verifier contract

The injected `Verifier` receives the `PaymentProof`, the seller npub and the
FIPS msg1 ephemeral, and returns a bool. A production verifier MUST check:

1. the mint signature / DLEQ on the proof;
2. NUT-11 P2PK is locked to the seller (`sigflag` `SIG_ALL`);
3. the payer signature covers the token, seller npub, payer npub, transport,
   msg1 ephemeral, `issued_at` and claimed steps (`docs/0003`);
4. the proof's keyset is the one it claims.

The stub verifier in the tests only checks a flag. That is enough to exercise
the ordering, not enough to trust.

## Ordering and failure paths

| Step | Failure | Result |
|---|---|---|
| amount/payer validation | `PaymentError` | nothing written |
| keyset `final_expiry` | `ProofRejected` | nothing written; refund the proof |
| verifier | `VerificationFailed` | nothing written |
| exposure cap | `ExposureExceeded` | nothing written |
| journal reserve | `ReservationInFlight` / `AlreadySettled` / `AlreadySpent` | the just-taken exposure is released; the original remains |
| all pass | — | `Receipt` with journal RESERVED + exposure outstanding |

Exposure is taken **before** the journal row so a crash overstates the cap
(`docs/0010`). If the journal refuses, the gate releases the exposure it just
took, so a replay does not consume the payer's cap.

## Receipt lifecycle

```
accept -> Receipt(journal RESERVED, exposure outstanding)
settle -> journal SETTLED, exposure released
reject -> journal SPENT,    exposure released
```

`settle` is called after the mint confirms (NUT-07). `reject` is called after a
detected double spend or an unrecoverable reservation. Both are explicit; the
gate never silently forgets a reservation.

## What it does not do

- **No real cryptography.** The verifier is a stub in the tests.
- **No mint.** There is no HTTP client, no `/checkstate`, no batched settlement.
- **No session credit.** It returns a `Receipt`; wiring `paid` to the session
  and the link gate is the next integration step.
- **No refund path.** A rejected-before-reserve proof is the caller's to refund.
- **No cross-mint netting.** Each mint/unit is separate.

## Tests

`sidecar/tests/test_payment.py` covers:

- accept records journal RESERVED and exposure outstanding;
- verification failure writes nothing;
- cap refusal happens before the journal;
- a replay releases the second exposure and keeps the first;
- settle closes both ledgers;
- reject marks SPENT and releases exposure;
- an expired keyset is rejected before the verifier runs;
- invalid amount and empty payer are refused.

## Next

1. A real verifier for a local test mint: signature/DLEQ, P2PK, NUT-07.
2. Wire `Receipt` to `Session.pay()` and the link gate's `paid` state.
3. A settlement worker with batching and a stale-reservation reconciler.
4. Exp F (mint stopped) and Exp G (`final_expiry`) against the test mint.
