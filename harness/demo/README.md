# Phase 1 demo — buyer exhausts, is cut, re-admits

Two-node FIPS lab plus the real Nutshell mint. The demo shows both the failure
and the crude workaround:

1. **Unpaid free ride.** The link is up and the session is `unpaid`; FIPS still
   forwards traffic. The demo measures the bytes and the zero charge.
2. **Real payment.** A 50 sat P2PK+DLEQ token is minted, cached, verified with
   the mint stopped, and accepted through `PaymentGate` → journal → exposure.
3. **Exhaustion.** One-packet metering until the 50 sat allotment is used.
4. **Durable eviction.** Deny → wait for ACL effective → disconnect. Ping stops.
5. **Prepaid re-admission.** A second real token was verified before the cut;
   ACL allow + handshake brings the link back.

Payment is out-of-band (Docker/mint, not over FMP). The demo is about admission
and exhaustion, not an in-band payment lane.

## Run

```sh
harness/demo/run-demo.sh
harness/demo/run-demo.sh --down
```

It takes about a minute: Nutshell mint, two offline token verifications, eight
one-packet steps, one eviction and one re-admission.

The script recreates the Exp C containers from scratch. Reusing them after
repeated deny/allow flapping can leave a handshake stuck; see the failed-run
note in the result.

## Expected numbers

| Metric | Value (2026-11-03) |
|---|---|
| Unpaid bytes forwarded | 14,274 B for 0 msat |
| Payment | 2 × 50 sat, offline, accepted |
| Paid bytes | 55,806 B |
| Overshoot | 5,806 msat (11.6 %, one ping step) |
| Evict | deny 786 ms + disconnect 996 ms; ping fails |
| Re-admit | 677 ms ACL + 1,077 ms link ≈ **1.75 s** |
| Link ids | 1 → 3 |

## Warnings

- `FakeWallet` only. No Lightning, no mainnet, no real value.
- The overshoot is a **measurement-step** artifact. A 40-packet batch version
  overshot 2.18×; per-packet brought it to 11.6 %. State the step in the offer.
- No `grace`: the cut is a durable eviction, not a pause. Patch (b) is still the
  product change.
- The result records a failed-run observation where a long deny window left the
  next handshake blackholed for >10 s. The demo avoids it with a short deny
  window; a control-socket admission path (patch (a)) is the real fix.

## Result

`results/DEMO-2026-11-03-buyer-exhausts.md`
