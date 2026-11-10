# Result: ACCOUNT — production host prototype, not a flight release

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Work:** durable npub accounts, strict offline P2PK policy, CRC journal
- **Status:** host prototype complete; 174 tests plus subtests pass

## Question

Can the host-side money/account primitives satisfy the next part of the balloon
readiness contract before porting into a real relay controller and flashing
flight boards?

## Raw harness output

Command:

```sh
python3 harness/exp-account/account_demo.py
```

The account accept and resume phases ran in **separate child processes**. All
amounts are synthetic test units; no mint contact occurs in this harness.

```json
{
  "accept": {
    "state": "dormant",
    "remaining_msat": "8770",
    "charged_msat": "1230",
    "link_id": null
  },
  "resume": {
    "on_reopen": {
      "state": "dormant",
      "remaining_msat": "8770",
      "link_id": null
    },
    "on_new_link": {
      "state": "paid",
      "link_id": "link-9",
      "remaining_msat": "8793",
      "used_msat": "1307",
      "charge_now_msat": "77"
    }
  },
  "offline_p2pk": {
    "valid_one_of_one": "accepted",
    "refund_reclaim": "rejected: P2PK reclaim path not allowed: refund",
    "locktime_reclaim": "rejected: P2PK reclaim path not allowed: locktime",
    "grouped_signing": "rejected: grouped/multisig-witness signing is not allowed",
    "unknown_extension": "rejected: unknown P2PK extension: future_reclaim"
  },
  "crc_journal": {
    "replay_same_process": "ReservationInFlight",
    "replay_after_reopen": "AlreadySettled",
    "pending_after_settle": 0,
    "torn_tail_pending": 0,
    "records_after_reopen": 1
  }
}
```

## Test output

```text
$ PYTHONPATH=./sidecar python3 -m pytest sidecar/tests -q
........................................................................ [ 41%]
............................................................. [ 76%]
........................................                                 [100%]
174 passed, 14 subtests passed in 0.26s
```

The 174 cases include the existing 135 sidecar cases as well as new account,
NUT-11 and append-only-journal cases. The previous harness variants for real
offline P2PK/DLEQ and deferred settlement (`F`, `TWOKEY`, `OUTAGE`, `EXPIRY`)
remain applicable; this result does not replace those cryptographic tests.

## Interpretation

1. **A durable npub account survives process restart and new link ids.**
   Reopening showed 8,770 msat DORMANT. A new link id resumed the same account,
   rather than minting a new paid balance. Subsequent charge/payment history
   was preserved exactly as 1,307 msat used and 8,793 msat remaining.
2. **Stricter NUT-11 validation is now executable.** One-of-one compressed-key
   locks pass; reclaim paths, grouped signing and unknown extensions fail before
   value can be trusted offline. The policy is intentionally narrower than a
   general Cashu receiver.
3. **The append-only journal gives usable evidence for an embedded design.**
   Same-process replay is refused, post-reopen replay after settle is refused,
   settled reservations are not pending, and a torn tail produces no pending
   entitlement. Full-history reopen preserves settled state, while compaction
   retains each key's latest settled/reserved state.
4. **This is not a deployed relay.** Account state, P2PK condition validation
   and the journal are now real modules and tests, but wiring them into the
   balloon's payment/session controller, radio forwarding logic and flash files
   remains separate work.

## Added artefacts

- `sidecar/tollgate_fips/account.py` — prepaid npub accounts and durable store.
- `sidecar/tollgate_fips/nut11.py` — strict offline P2PK admission policy.
- `sidecar/tollgate_fips/appendlog.py` — bounded-record CRC append-only journal.
- `sidecar/tests/test_account.py`, `test_nut11.py`, `test_appendlog.py`.
- `harness/exp-account/account_demo.py` — cross-process demo.
- `docs/0020-balloon-production-readiness.md` — production plan/checklist.
- `docs/0021-npub-prepaid-accounts.md` — API and proof boundaries.

## Open production gates (do not claim them complete)

- Wire these modules into one configured relay controller and enforce account
  state in its actual request/forwarding path.
- Preserve the exact declared chargeable-frame policy and exclude policy drops.
- Exercise the strict NUT-11 verifier against extra real-mint vectors and
  keyset rotation while offline.
- Bind per-peer payment verification to caller identity; exercise relayed
  payer binding rather than only direct FIPS presentation.
- Validate OS reboot, corrupt-store behavior, key lifecycle and per-account caps.
- Measure embedded flash commit/compaction durability with actual power cuts.
- Prove actual LR2021/Wirehair time-to-pay/metering over real contact windows.
- Complete instrumented soak, operator recovery runbooks and signed release
  artifacts with no debug keys.

See `docs/0020-balloon-production-readiness.md` for the full host/firmware/
hardware checklist.
