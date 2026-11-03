# 02 — Tor

**Question:** does the gate behave the same when the transport address is
`127.0.0.1` and the real peer is an onion service?

**Status:** not started. Phase 2.

## Topology

```
seller (fipsd, tor)  <== onion service ==>  Tor network  <==>  buyer (fipsd, tor)
```

Both nodes run a Tor client or a `tor` transport in FIPS. The seller publishes
an onion endpoint (see P1). The buyer dials it.

## Why this is the sharpest test of "per transport is scope, not code"

Inbound Tor connections arrive from `127.0.0.1`. Every buyer looks the same at
L0. Any gate that keys on the transport address is useless here; only the npub
at L1 is an identity. If the design survives Tor, it survives the general case.

## Steps

1. Bring up both nodes with the Tor transport and a control socket.
2. Advertise the seller's onion endpoint.
3. Run the shared acceptance test (`../README.md`): unpaid → paid → grace →
   paid → evicted.
4. Record the transport counters and the per-link counters. Confirm the peer
   address is loopback and the identity is the npub.
5. Kill the Tor daemon mid-session. Record what happens to the link and to the
   payment lane. This is a preview of Exp F (mint stopped) over an unreliable
   path.

## Pass criteria

- [ ] Same state-machine log as TCP.
- [ ] Counters reconcile as FMP frame bytes.
- [ ] The gate never uses `127.0.0.1` to distinguish two buyers.
- [ ] Endpoint advertisement carries the onion address, not a port.

## Extra observation

Tor adds latency and jitter. Record time-to-admit and time-to-`grace` so the
pause TIP can state a range, not a TCP-only number.
