# Result: PD — pause with payment, no disconnect

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** pause with real payment — unpaid enforced, exhaust, pause, renew
- **Node(s):** `lt-pause-a` (buyer), `lt-pause-b` (seller/transit), `lt-pause-c` (service)
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local patch (b)
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **TollGate commit:** n/a
- **Repo commit:** capstone commit
- **Status:** pass

## Question

Can `unpaid` be enforced **without disconnecting**, and can a paid session be
paused and renewed while the link stays up? This is the end-to-end shape the
design has been aiming at.

## Setup

Chain A–B–C. B is the patched transit node and tree root; A is the buyer, C is
the service. B's patch (b) control command `set_forwarding` blocks or allows A's
transit. A→B traffic is local delivery at B, so it remains the payment/local
path when transit is blocked.

The path is warmed with `fipsctl probe <C>` before the first check, because raw
ICMP did not trigger mesh discovery in this lab.

Payments are real 50 sat P2PK+DLEQ tokens locked to B's compressed key
(`025dd0ec...9dff`), verified with the mint stopped and accepted by
`PaymentGate` → journal → exposure. Payment is out-of-band; the gate runs on the
host for lab convenience.

```sh
harness/pause/run-pay-demo.sh
```

## Raw output

```
unpaid: a->c=False a->b=True block=blocked
payment 1: offline=True accepted=3 amount=50 sat
paid: a->c=True
session: bytes=56378 used=56378 msat state=grace pings=17
pause: a->c=False a->b=True link=4 (pre=4, 3609 ms)
payment 2: offline=True accepted=3 amount=50 sat; a->c=True link=4

{
  "date": "2026-11-03",
  "fips_version": "0.6.0-dev (rev 2ba790b221)",
  "nodes": {
    "a": "npub1hs6dzx86tn2c7mt3wntw2tt7m6seyua78pwfhagkk08v2yur9m0smvtmad",
    "b": "npub1thgwcxk5x45r9vusqzksmxnewfkgzhrdf4dlnc75ky96g6swnhlszjzgrw",
    "c": "npub1pqf3mx4ayr68ldz39l3unrgkn0rhe8ch7437wv6pav6tpj0777lsrznlup"
  },
  "unpaid": {"a_to_c": false, "a_to_b": true, "forwarding": "blocked"},
  "payment_1": {"offline": true, "accepted": 3, "amount": 50,
                "replay_before_settle": "ReservationInFlight",
                "replay_after_settle": "AlreadySettled"},
  "paid": {"a_to_c": true},
  "session": {"allotment_msat": "50000", "billable_bytes": 56378,
              "used_msat": "56378", "overshoot_msat": "6378",
              "pings": 17, "state": "grace"},
  "pause": {"a_to_c": false, "a_to_b": true, "forwarding": "blocked",
            "pause_ms": 3609, "link_id": 4, "link_id_pre_pause": 4,
            "link_preserved": true},
  "payment_2": {"offline": true, "accepted": 3, "amount": 50,
                "replay_before_settle": "ReservationInFlight",
                "replay_after_settle": "AlreadySettled"},
  "resume": {"a_to_c": true, "link_id": 4, "link_id_preserved": true},
  "link_id_before": 2,
  "link_id_pre_pause": 4
}
```

## Measurements

| Phase | Result |
|---|---|
| Unpaid, transit blocked | A→C **fail**, A→B **pass** |
| Payment 1 | 3 proofs accepted offline, 50 sat |
| Paid, transit allowed | A→C **pass** |
| Paid traffic | 56,378 FMP bytes, 17 one-packet steps |
| Allotment | 50,000 msat |
| Overshoot | 6,378 msat (12.8 %, one step) |
| Exhaustion | `paid → grace` |
| Pause | A→C **fail**, A→B **pass** |
| **A–B link during pause** | **preserved, id 4** |
| Pause command + checks | 3,609 ms |
| Payment 2 | 3 proofs accepted offline, 50 sat |
| Resume | A→C **pass**, link id 4 preserved |
| Disconnect at any point | **none** |

## Interpretation

1. **`unpaid` is enforceable without a cut.** Blocking A's transit at B stops
   A→C while A→B (the local/payment path) and the A–B link stay. The earlier
   Phase 1 demo had to disconnect; patch (b) removes that requirement.
2. **Real offline payment restores transit.** Two Nutshell P2PK+DLEQ tokens
   verified with the mint stopped; `allow` made A→C work. The payment lane is
   the local path, so it never left.
3. **Pause preserves the link.** At exhaustion, A→C failed, A→B passed, and the
   A–B link id was unchanged. No `disconnect` was issued. `resume` after the
   second payment restored A→C with the same link.
4. **The link id changed during setup, not during the pause.** It went 2 → 4
   while the chain/path warmed; the pause compared 4 → 4. The result is about
   the pause, not startup churn.
5. **Metering must freeze when forwarding is blocked.** B's per-link counter
   still counts frames it refuses to forward. A real gate must not bill those:
   snapshot at the policy change, or subtract a policy-drop counter. The local
   patch has no such counter yet; the demo avoids the issue by only metering
   while A→C works.
6. **The overshoot is one measurement step.** 12.8 % for one ping step; the spec
   must state the step and keep it small.
7. **This is the design's `grace` shape.** Forwarding blocked, link and payment
   lane open, renewal possible without a new handshake. The remaining work is
   productionising the hook, not proving the concept.

## Caveats

- One run, one chain, one root order. Repeat with different roots and a longer
  chain.
- Local, unmerged patch. Not submitted to `jmcorgan/fips`; no public interaction.
- Payment is out-of-band; no in-band payment lane over FMP.
- `FakeWallet`, no Lightning, no mainnet, no real value.
- No policy-drop counter; metering of blocked frames needs one.
- `fipsctl probe` is used to warm discovery; a production gate should not depend
  on a diagnostic command.

## Follow-ups

- [x] Patch (b) and sidecar `pause`/`resume`.
- [x] End-to-end unpaid → paid → pause → renew without a disconnect.
- [ ] Add `drop_policy_blocked_{packets,bytes}` and freeze metering on pause.
- [ ] Add `fipsctl set-forwarding` so the sidecar needs no raw socket.
- [ ] Repeat 3–5 times; try different root orders.
- [ ] Re-run over TCP and Ethernet.
- [ ] Prepare the out-of-band Signal write-up (do not send until reproducible).

## Artefacts

- `harness/pause/pay_demo.py`
- `harness/pause/run-pay-demo.sh`
- `patches/0001-per-peer-forwarding.patch`
- `harness/mint/` (real test ecash + offline verifier)
- `results/PB-2026-11-03-per-peer-forwarding.md`
- `results/F-2026-11-03-offline-verify.md`
