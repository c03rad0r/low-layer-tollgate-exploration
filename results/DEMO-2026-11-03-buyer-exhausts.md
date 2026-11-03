# Result: DEMO — buyer exhausts, is cut, and re-admits with a real payment

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** Phase 1 exit demo — pay, admit, exhaust, cut, re-admit
- **Node(s):** `lt-exp-c-seller`, `lt-exp-c-buyer`; Nutshell mint `lt-mint`
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`)
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **TollGate commit:** n/a
- **Repo commit:** Phase 1 demo commit
- **Status:** pass, with the documented limitation that `unpaid` is not
  enforceable without a FIPS change

## Question

With zero FIPS changes, can a seller sell a link, stop forwarding at exhaustion,
and require a new payment before re-admission? The plan predicted the answer is
"only crudely, by disconnecting". This demo measures how crude.

## Setup

Two-node UDP lab on a private Docker bridge:

```
seller (passive)  <---- UDP ---->  buyer (auto_connect)
```

Both use strict ACLs. The seller's compressed NUT-11 pubkey is
`03d05bdb...3ba4`. The buyer is simulated by the host orchestrator: it mints a
50 sat P2PK+DLEQ token to the seller, caches the keyset keys, stops the mint,
and the seller verifies the token offline. The proofs go through
`PaymentGate` → journal → exposure. Two tokens are minted: one for the paid
period, one prepaid for re-admission.

Payment is **out-of-band** (the wallet talks to the mint over Docker, not over
FMP). This demo tests admission and exhaustion, not an in-band payment lane.

```sh
harness/demo/run-demo.sh
```

## Raw output

```
unpaid: ping=True bytes=14274 charged=0 state=unpaid
payment 1: offline=True accepted=3 amount=50 sat state=paid
payment 2 (prepaid): offline=True accepted=3 amount=50 sat
session: bytes=55806 used=55806 msat state=grace pings=8
evict: mode=deny+disconnect cut=996 ms ping=False
re-admitted: acl=677 ms mode=explicit link=1077 ms id=3 ping=True state=paid

{
  "date": "2026-11-03",
  "fips_version": "0.6.0-dev (rev 2ba790b221)",
  "seller_npub": "npub16pdakpwe28famj7j392f5xkqxc35zhal4g3k2yna049wcxn58wjqsjm9wu",
  "buyer_npub": "npub16584pelypd8qd0u7vyfye7vam3jtschup0heyuez20m59xlmhzks2y5wfa",
  "link_id_initial": 1,
  "unpaid": {
    "ping": true,
    "billable_bytes": 14274,
    "charged_msat": "0",
    "state": "unpaid",
    "note": "FIPS forwarded while unpaid; no pause hook"
  },
  "payment_1": {
    "offline": true,
    "accepted": 3,
    "amount": 50,
    "replay_before_settle": "ReservationInFlight",
    "replay_after_settle": "AlreadySettled"
  },
  "payment_2_prepaid": {
    "offline": true,
    "accepted": 3,
    "amount": 50,
    "replay_before_settle": "ReservationInFlight",
    "replay_after_settle": "AlreadySettled"
  },
  "session": {
    "allotment_msat": "50000",
    "billable_bytes": 55806,
    "used_msat": "55806",
    "overshoot_msat": "5806",
    "pings": 8,
    "state": "grace"
  },
  "evict": {
    "mode": "deny+disconnect",
    "acl_wait_ms": 786,
    "cut_ms": 996,
    "ping_after": false
  },
  "readmit": {
    "acl_ms": 677,
    "mode": "explicit",
    "link_ms": 1077,
    "link_id": 3,
    "ping": true,
    "session_state": "paid"
  }
}
```

## Measurements

| Phase | Result |
|---|---|
| Link up, session `unpaid` | ping succeeds; **14,274 bytes forwarded for 0 msat** |
| Payment 1 | 3 proofs accepted offline, 50 sat |
| Payment 2 (prepaid) | 3 proofs accepted offline, 50 sat |
| Paid traffic | 55,806 FMP bytes over 8 one-packet steps |
| Allotment | 50,000 msat (50 sat at 1 B/msat) |
| Overshoot | **5,806 msat (11.6 %)** — one measurement step |
| Exhaustion | `paid → grace` |
| Durable evict | deny → ACL effective 786 ms → disconnect 996 ms |
| Ping after cut | **fail** |
| Re-admit ACL | 677 ms |
| Re-admit link | 1,077 ms, explicit |
| **Total re-admit** | **≈1.75 s** |
| Link ids | 1 → 3 |
| Session after re-admit | paid (prepaid token) |

## Interpretation

1. **`unpaid` is not enforceable without a FIPS change.** With the link up and
   the session `unpaid`, FIPS forwarded 14,274 bytes and the session charged 0.
   There is no per-peer forwarding role, so the seller cannot block this peer
   while keeping the link. This is the load-bearing gap; patch (b) is the
   product change, not a convenience.
2. **Real offline payment works.** Two real P2PK+DLEQ tokens were accepted with
   cached keys and the mint stopped. The journal refused a replay across a
   restart and the exposure was exact. This is no longer a stub.
3. **The crude workaround is a durable cut plus a handshake.** Deny → wait for
   the ACL → disconnect stopped the traffic in ~1 s. Re-admission with a
   prepaid token cost ~1.75 s (0.68 s ACL + 1.08 s link). That is the number
   P4 should quote, and it is why `grace` needs patch (b).
4. **The measurement step dominates the overshoot.** Per-packet metering
   reduced the overshoot from the first attempt's **2.18×** (a 40-packet batch)
   to **11.6 %** (one ping step). A production gate must state its step; a
   per-frame meter would be smaller still. This is a protocol-visible number.
5. **Prepaid renewal avoids the payment gap.** The second token was verified
   before exhaustion, so re-admission did not wait for a mint round trip. In a
   real deployment the buyer should top up before `grace`, not after `evicted`.

## Failed-run note: deny storms can blackhole the next handshake

Earlier attempts kept the buyer denied for 5–10 s while the token was minted and
verified. After the ACL was changed to allow, the buyer's explicit
`fipsctl connect` was logged as initiated but no handshake reached the seller
for more than 10 s; the seller's ACL was correct (`allow_entries=1`,
`deny_all=true`). A manual `disconnect` + `connect` later established the link.
This is consistent with the msg1 rate limiter / client backoff, but it was not
isolated.

The final demo avoids the storm by admitting first (showing the free ride) and
keeping the post-eviction deny window short. It is another argument for a
control-socket admission path (patch (a)) rather than relying on ACL files and
client retries.

## Caveats

- Payment is out-of-band. It does not test an in-band payment lane over FMP.
- `FakeWallet`; no Lightning, no mainnet, no real value.
- One run. The overshoot depends on the step; the ACL/handshake numbers vary
  with tick phase and client backoff.
- No NUT-07 settlement; the journal records acceptance and the demo settles
  locally.
- No Ethernet/BLE. Those are where the in-band payment lane matters most.

## Follow-ups

- [x] Real offline payment instead of a stub.
- [x] Durable eviction and re-admission with a prepaid token.
- [ ] Patch (b): block one peer's forwarding while keeping the link, then re-run
      this demo as `unpaid → paid` without a cut.
- [ ] Exp G: keyset `final_expiry`.
- [ ] Repeat over TCP and Ethernet.
- [ ] A real NUT-07 settlement worker.

## Artefacts

- `harness/demo/demo.py`
- `harness/demo/run-demo.sh`
- `harness/mint/` (mint, token, offline verifier, gate adapter)
- `results/F-2026-11-03-offline-verify.md`
- `results/C-2026-11-03-cut-readmit.md`
