# Result: EXPIRY — a receiver can reject at deadline while the mint still accepts

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-EXPIRY (docs/0019, decision D3)
- **Mint:** Nutshell 0.21.0, `FakeWallet`, test ecash only
- **Status:** completed one-expiry arm

## Question

Which component enforces a settlement window for P2PK notes accepted offline:
the receiver, or the mint's `final_expiry`?

## Setup

A real 100 sat P2PK+DLEQ token (three proofs) was minted against the same
keyset. `final_expiry` was then set to 90 seconds in the future. The seller
offline-verifies and tries acceptance with a 3,600-second settlement window and
a 30-second window. After expiry, the same checks run again and the note is
redeemed with the seller's key.

```sh
TOKEN_SRC=/tmp/opencode/token.txt \
  harness/exp-expiry/run-expiry.sh
```

The token content is not republished. Only its real P2PK verification and the
redemption results are recorded.

## Raw output

### 3,600-second window: refused

```text
"keyset_final_expiry": [1794302459]
"accepted": [
  "ProofRejected: keyset expires inside the settlement window; refund it instead",
  "ProofRejected: keyset expires inside the settlement window; refund it instead",
  "ProofRejected: keyset expires inside the settlement window; refund it instead"
]
```

### 30-second window: accepted

```text
"accepted": [true, true, true]
```

### After expiry: the receiver refuses, redemption still succeeds

```text
"checked_at": 1794302466
"accepted": [
  "ProofRejected: keyset expires inside the settlement window; refund it instead",
  "ProofRejected: keyset expires inside the settlement window; refund it instead",
  "ProofRejected: keyset expires inside the settlement window; refund it instead"
],
"redeem": {"ok": true, "balance": "99 sat", "unit": "sat"}
```

100 sat gross became 99 sat on redemption (`input_fee_ppk=100`).

## Interpretation

1. **The mint is permissive here, not authoritative on expiry.** Nutshell 0.21.0
   accepted this P2PK redemption after the keyset's expiry. A seller that waits
   for the mint to say "expired" can already have sold credit too late.
2. **The receiver predicate is the load-bearing guard.** With a 3,600-second
   window the same notes were rejected immediately; a 30-second window admitted
   them. This must be checked at admission, before forwarding.
3. **`final_expiry` is a settlement deadline, not a link clock.** It should be
   `now + settlement_window` or later. Connection gaps should be handled with a
   separate monotonic session deadline; do not make a contact wait outlive its
   settlement opportunity.
4. **Settlement timing is part of pricing an offline sale.** The amount of
   unconverted token value depends on both its time-to-expiry and the next
   possible uplink, not only its denomination.

## Decision for D3

Enforce `final_expiry >= now + settlement_window + contact_skew` at admission,
and reject unknown keysets or ones outside the seller's allow-list. Choose the
settlement window from the longest plausible offline stint; tune the actual
window with fleet data, not a universal constant.

## Caveats and follow-ups

- One expiry (~90 s), one keyset, one token. No varied expiry series.
- The token was created before the short expiry was applied, so this tests
  deferred settlement rather than minting at the last possible instant.
- Keyset rotation while offline was not exercised here; it remains a separate
  required experiment before provisioning a long offline flight.
- No real funds, production mint, hardware RTC, or power-failure timing.

## Artefacts

- `harness/exp-expiry/run-expiry.sh`, `expiry_accept.py`.
- `results/G-2026-11-03-final-expiry.md` (the original Nutshell behavior check).
