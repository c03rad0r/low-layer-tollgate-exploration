# Result: RELAY — reserve-before-credit enforced at the request path

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** connect accounts, offline P2PK policy and CRC proof journal
  through `PaymentGate` to one app-relay controller.
- **Status:** host integration completed, 185 tests plus subtests

## Raw output

```sh
python3 harness/exp-account/relay_demo.py
```

The harness uses synthetic amounts and a structural valid-lock verifier, not
real money or a DLEQ oracle. Its purpose is integration order and accounting;
the real-mint cryptographic evidence is documented separately under TWOKEY,
OUTAGE, EXPIRY and F.

```json
{
  "unpaid": {"allowed": false, "state": "unpaid"},
  "after_valid_payment": {
    "allowed": true,
    "charged_msat": "10",
    "remaining_msat": "990"
  },
  "cross_peer_replay": "ReservationInFlight",
  "exhausted": {
    "allowed": true,
    "state": "grace",
    "remaining_msat": "0"
  },
  "after_exhaustion": {"allowed": false, "charged_msat": "0"},
  "after_reopen": {
    "state": "dormant",
    "remaining_msat": "2000",
    "used_msat": "1000"
  },
  "resumed_new_link": {
    "allowed": true,
    "state": "paid",
    "remaining_msat": "1990"
  },
  "pending_before_settlement": 2
}
```

## Verification

```text
$ PYTHONPATH=./sidecar python3 -m pytest sidecar/tests -q
..................................................................... [ 37%]
............................................................. [ 70%]
.......................................................                  [100%]
185 passed, 14 subtests passed in 0.33s
```

## What this proves

- `AppRelayController` does not let an unpaid peer forward.
- A valid accepted proof gives its FIPS presenter a credited account, and one
  charged 100-byte frame consumes exactly 10 msat at 10 B/msat.
- Replaying a spent proof under a second identity does not produce new credit.
- Exhaustion changes paid → grace and the following frame is blocked rather
  than becoming a free fallback. No billing is charged to a blocked frame.
- A second proof resumes allowance. After closing/reopening the account store,
  state is DORMANT and `used_msat` remains exactly 1,000; a new link id resumes
  the existing account (remaining 1,990 msat), not a fresh one.
- `CrcNullifierJournal` implements `PaymentGate`/`SettlementWorker`'s
  Reservation interface using CRC storage without changing the durable order:
  verify → exposure → reservation → credit.
- Pending before settlement is exactly two, one per accepted proof, not a
  fresh reservation for replay attempts.

## What it does not prove

- There is no real token, Nutshell interaction or on-radio tx in this harness.
  Its verifier is a structural test adapter.
- There is no real FIPS socket/mux integration yet. Authenticated peer and
  link identity are supplied to the controller in this test; the E-BIND result
  shows where they can come from in a live FIPS peer table.
- No agreement yet on which exact external/app request bytes constitute a
  chargeable frame; the real service must supply them at the wire boundary.
- No mesh-wide claim: this controller is an **application request-path policy**,
  not a claim to have gated all alternate routes for a peer.
- No flash power-cut, MCU memory, CPU or RF-window evidence.

## Artefacts

- `sidecar/tollgate_fips/relay.py`
- `sidecar/tollgate_fips/appendlog.py` (`CrcNullifierJournal`)
- `sidecar/tests/test_relay.py`
- `harness/exp-account/relay_demo.py`
- `docs/0022-app-relay-integration.md`
