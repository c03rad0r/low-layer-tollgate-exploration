# 01 — TCP

**Question:** can a `scope=link` session be admitted, metered and torn down over
the TCP transport, with both ends' counters reconciling?

**Status:** partial. Cut, durable eviction and re-admit pass over TCP
(`../../results/01-tcp-2026-11-03.md`). Payment, beacon and the full four-state
demo are still pending.

## Topology

```
seller (fipsd, tcp)  <---- TCP ---->  buyer (fipsd, tcp)
        |                                   |
   control.sock                        control.sock
        |                                   |
   tollgate-fips (sidecar)             traffic gen
```

Two nodes is enough. A third (`relay`) is optional for Exp I.

## Why TCP first

- It is the transport with the fewest moving parts: no radio, no NAT, no
  onion service.
- It exposes the port question directly, which is why P1 removes the port and
  adds endpoint advertisement.
- Frame boundaries are stream-based, so this experiment is where the
  "FMP frame, not payload" boundary is easiest to get wrong. That makes it a
  good first test of the metering rule.

## Steps

1. Start `fipsd` on both nodes with the TCP transport enabled and a known
   control socket.
2. Start `tollgate-fips` on the seller. It admits the buyer via
   `peers.allow`, then reads `fipsctl show links` for the link's counters.
3. Establish the link. Confirm the session is `unpaid` and that chargeable
   forwarding is blocked.
4. Pay a test-mint token. Confirm `paid`.
5. Generate a known number of bytes. Record both counters before and after.
6. Exhaust the allotment. Confirm `grace`, then renew.
7. Let grace expire. Confirm `evicted` and that the link is closed.
8. Compare buyer and seller bytes. Tolerance: the framing difference between
   the two ends, stated in the result file.

## Pass criteria

- [ ] Session reaches all four states in order.
- [ ] Buyer's counter and seller's counter agree within the stated tolerance.
- [ ] Metered bytes equal the FMP frame count, not the payload count.
- [ ] Renewal in `grace` does not create a new link.
- [ ] Eviction closes the link and the buyer can re-admit.

## Lab

`harness/exp-tcp/` runs the TCP pair and reuses `harness/exp-c/exp_c.py`.

## Known failure to document

With FIPS 0.5.x there is no pause hook. Step 3 and step 6 will be implemented
with `disconnect`, which also closes the payment lane. That failure is the
evidence for P4 and for FIPS patch (b). Do not hide it; record the time from
exhaustion to `disconnect` and whether a re-admit was possible.

## Result file

`../../results/01-tcp-2026-11-03.md`
