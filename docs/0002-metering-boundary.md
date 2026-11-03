# 0002 — The metering boundary: wire bytes, per direction

Status: settled for the protocol. Empirical check: Exp A.

## The rule

For `scope=link`, a TollGate meters **FMP frame bytes**:

```
chargeable bytes = 4 (common prefix)
                 + 12 (remaining header: receiver idx + counter + type/timestamp)
                 + payload
                 + 16 (AEAD tag)
```

summed over **chargeable frames only**, in the directions the session covers.

- **Chargeable:** `SessionDatagram` and session-layer payload frames
  attributable to the customer.
- **Not chargeable:** `Heartbeat`, MMP `SenderReport` / `ReceiverReport`,
  `TreeAnnounce`, `FilterAnnounce`, `LookupRequest` / `LookupResponse`,
  `Disconnect`, rekey.

A customer does not pay for the seller's routing chatter, and does not pay
twice for a retransmitted frame that consumed wire twice.

**Policy-dropped frames are not chargeable.** A frame the seller refuses to
forward because the peer is paused consumed link bytes but delivered no
transit. The link counter still includes it (the drop is after the counter), so
a gate MUST freeze its meter at the policy change or subtract a
`drop_policy_blocked_*` counter. Those bytes are rate/abuse control, never
revenue. The local patch (b) does not yet expose that counter.

## Why wire bytes and not payload bytes

1. **It is the seller's cost.** Air time, battery, ISP bytes and the AEAD/header
   overhead are all real. Charging payload bytes makes the seller subsidise
   framing, and the distortion is worst where it matters: a BLE frame carrying
   a 5-byte inner header in a ~21-byte frame is ~76 % overhead. MONAD reached
   the same conclusion independently with `in_bytes_per_millisat` and
   `out_bytes_per_millisat`.
2. **Both sides measure the same thing.** Each end sees the same frames on the
   link, so the counters reconcile without either side trusting the other's
   parser. Payload bytes require agreement on a boundary, which is a trust
   problem disguised as arithmetic.
3. **It is unambiguous under rekey, drain, MTU change and retransmission.**
   A frame is a frame. A retransmission consumed wire twice and is charged
   twice. A frame that crossed during a drain window still crossed.
4. **It removes the "whose header is it" argument**, because the header is part
   of what crossed.

## What FIPS already counts

Verified in source on the 0.6.0-dev tree (mirrored by fleet 0.5.3 behaviour):

- UDP receive: `stats.record_recv(len)` where `len` is the `recvmsg` return —
  the UDP payload, i.e. the FMP frame. `src/transport/udp/mod.rs:644,707`.
- UDP send: `record_sent` is fed the length actually written.
- Per-link send: `peer.link_stats_mut().record_sent(bytes_sent)` where
  `bytes_sent` is the length of `wire_packet`, the sealed FMP frame
  (`src/node/mod.rs:4592,4664`).
- Ethernet receive: `stats.record_recv(len)` is taken **before** the 3-byte
  FIPS frame header is stripped (`src/transport/ethernet/mod.rs:1275`), so it
  includes that header and excludes the 14-byte Ethernet MAC header (SOCK_DGRAM
  removes it).

So FIPS counters sit at the FMP boundary: **FMP frame bytes, excluding
medium encapsulation.** That is exactly the unit this spec wants, which means
an implementation can use the daemon's own counters rather than re-counting.

Encapsulation overhead is medium-specific and belongs in the medium spec:

| Medium | Added per frame, outside the counter |
|---|---|
| UDP over IPv6 | 8 + 40 = 48 B |
| TCP | 20 + 20 = 40 B (plus framing effects) |
| Ethernet | 14 B (+ FCS) |
| BLE L2CAP | L2CAP header + radio overhead |

A seller who wants to recover encapsulation cost MUST say so in the
advertisement, e.g. `["overhead","udp",48]`. Default: not charged.

## Direction

`["direction","both"|"in"|"out"]`, default `both` for link sales. Air time on
Ethernet and BLE is roughly symmetric; a WAN uplink is not. Making it explicit
avoids the "you charged me for my own upload" argument.

## Pricing units

Express the rate as **bytes per millisat**, not sats per byte. Integer sats per
byte cannot represent sub-sat rates, and step-rounding biases whichever side
the rounding favours. `step_size` remains a *billing* granularity, never a
*measurement* granularity.

The **measurement step** (per frame, or the polling interval if counters are
batched) bounds the overshoot at exhaustion. A batched 40-packet step overshot a
50 sat token by 2.18× in the Phase 1 demo; per-packet metering reduced it to one
packet. State the step in the offer.

## What this means for implementations

A sidecar that reads `fipsctl show links` gets frame bytes for free — but only
in aggregate per link, not per frame class. Splitting chargeable from
non-chargeable frames requires either:

- a per-class counter in FIPS (patch (d), not yet planned), or
- the sidecar subtracting a modelled control-frame rate, which is
  approximate and should be labelled as such.

Until then, link sessions SHOULD price an all-frames rate and state it as such.
