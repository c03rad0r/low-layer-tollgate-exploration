# TIP: Wire-byte metering for link sessions

- **Target repo:** `OpenTollGate/tollgate`
- **Status:** Draft for PR
- **Depends on:** scope (P2)
- **Experiment citations:** Exp A (`results/A-2026-11-03-counter-boundary.md`),
  PD (`results/PD-2026-11-03-pause-payment.md`), PB
  (`results/PB-2026-11-03-per-peer-forwarding.md`),
  `docs/0002-metering-boundary.md`, `docs/0007-current-enforcement.md`

## Abstract

Define the metered unit for `scope=link` normatively: **FMP frame bytes at the
transport boundary, per direction, over chargeable frames only**, priced in
**bytes per millisat**. Define which frames are chargeable, how direction is
declared, and what is outside the count.

## Motivation

Without a normative boundary, buyer and seller will each believe a different
number is correct:

- payload vs frame;
- including or excluding medium encapsulation;
- counting control traffic or not;
- rounding each frame up to a sat;
- charging retransmissions once or twice.

Each disagreement is a dispute the protocol cannot resolve after the fact,
because the bytes are gone. The boundary has to be stated before the first
session, not negotiated per sale.

Wire bytes are also the seller's actual cost: air time, battery, uplink bytes
and AEAD/header overhead. MONAD reached the same conclusion independently and
meters `in_bytes_per_millisat` / `out_bytes_per_millisat`.

## Specification

### 1. The unit

For a `scope=link` session, the metered quantity is:

```
chargeable_bytes = Σ over chargeable frames of FMP_frame_length
```

where

```
FMP_frame_length = 4  (common prefix)
                 + 12 (remaining header: receiver idx, counter, type/timestamp)
                 + payload_length
                 + 16 (AEAD tag)
```

The count is taken **at the transport boundary** — the datagram handed to, or
returned from, the socket. It **excludes** medium encapsulation:

| Medium | Excluded from the count | Included |
|---|---|---|
| UDP/IPv6 | 8 + 40 = 48 B | FMP frame |
| TCP | 20 + 20 = 40 B (plus framing effects) | FMP frame |
| Ethernet | 14 B MAC header (+ FCS) | FMP frame (the 3-byte FIPS frame header is part of the FMP frame) |
| BLE | L2CAP header + radio overhead | FMP frame |

A seller that wants to recover encapsulation cost MUST advertise it
explicitly, e.g. `["overhead","udp",48]`. Default: not charged.

### 2. Chargeable frames

**Chargeable:**

- `SessionDatagram` and other session-layer payload frames attributable to the
  customer.

**Not chargeable:**

- `Heartbeat`
- MMP `SenderReport` / `ReceiverReport`
- `TreeAnnounce`
- `FilterAnnounce`
- `LookupRequest` / `LookupResponse`
- `Disconnect`
- rekey frames
- frames dropped by the seller's own forwarding policy (a paused peer). They
  consume link bytes but deliver no transit; the gate MUST freeze/subtract them
  and never bill them as revenue. Patch (b) exposes a node-wide `drop_policy_blocked_{packets,bytes}` counter
  with per-peer `policy_blocked_by_peer` attribution, and the reference meter
  subtracts the window delta so paused frames are billed at zero.

Rationale: a customer does not pay for the seller's routing chatter, and does
not pay for the control traffic that keeps the seller's own mesh alive.

### 3. Direction

An offer MAY carry:

```json
["direction", "both" | "in" | "out"]
```

- `in`: bytes received by the seller from the customer.
- `out`: bytes sent by the seller to the customer.
- `both` (default for `scope=link`): the sum.

The session MUST mirror the direction. A seller that bills `both` MUST count
both directions at the same boundary.

Ethernet and BLE air time is roughly symmetric; a WAN uplink is not. Making the
direction explicit avoids the "you charged me for my own upload" dispute.

### 4. Rate and rounding

The price is expressed as **bytes per millisat**:

```json
["rate", "<bytes_per_millisat>"]
```

- The rate MUST be a positive rational or decimal string. It MUST NOT be
  constrained to an integer number of sats per byte: sub-sat rates exist and
  integer step-rounding biases whichever side the rounding favours.
- `step_size` remains a **billing** granularity (how often a balance is
  decremented), never a **measurement** granularity. Frames are counted
  individually; steps are settled in aggregate.
- The **measurement step** bounds the overshoot at exhaustion: one frame if
  metering per frame, one polling interval if counters are batched. An
  implementation MUST state the step in the offer. A batched 40-packet step
  overshot a 50 sat token by 2.18× in Exp C's demo; a per-packet step reduced
  it to one packet.
- Implementations SHOULD carry the remainder across steps rather than rounding
  each frame or each step.

### 5. Retransmission and duplication

A frame that crossed the wire twice was paid for twice. Retransmissions,
duplicates and rekey-adjacent copies are charged per crossing. Implementations
MUST NOT deduplicate by content.

A frame that crossed during a drain window still crossed and is chargeable.

### 6. Reconciliation

Both ends see the same frames on the link. A seller SHOULD expose its counter
to the buyer, and a buyer SHOULD compare. Disagreement beyond a stated tolerance
SHOULD pause the session rather than silently continue. The protocol does not
require a third-party auditor.

### 7. Relationship to FIPS counters

FIPS already counts at this boundary:

- UDP recv `stats.record_recv(len)` at `src/transport/udp/mod.rs:644,707`;
- per-link send `peer.link_stats_mut().record_sent(bytes_sent)` at
  `src/node/mod.rs:4592,4664`;
- Ethernet recv before the 3-byte FIPS header is stripped, at
  `src/transport/ethernet/mod.rs:1275`.

So an implementation MAY use the daemon's counters. It MUST NOT re-count at a
different boundary and call the result the same thing.

**Known limitation:** current counters are aggregate per link, not per frame
class. Splitting chargeable from non-chargeable frames requires either a
per-class counter (not yet planned) or modelling the control-frame rate.
Until a per-class counter exists, a `link` session SHOULD price an all-frames
rate and say so in the offer.

## Backwards compatibility

This TIP adds fields. Absent `direction`, `both` applies. Absent `rate`, the
offer's existing price applies, but it is then not a wire-byte price and the
seller MUST NOT claim wire-byte metering.

## Security considerations

- A buyer can under-report its own counter. The seller's counter is the one
  that bills. Reconciliation is a courtesy, not a consensus.
- A seller can over-report. The buyer's remedy is to leave; the protocol has no
  fraud proof. The exposure cap bounds a single session's loss.
- Metering must not be used to distinguish traffic content. Count frames, not
  payloads.

## Citation

- Exp A: `results/A-2026-11-03-counter-boundary.md`; source table in
  `docs/0002-metering-boundary.md` and `docs/0007-current-enforcement.md`.
- Measurement-step overshoot: `results/PD-2026-11-03-pause-payment.md`.
- Policy-dropped frames and the per-peer counter:
  `results/PB-2026-11-03-per-peer-forwarding.md`.
- Ethernet transport uses the same FMP frame boundary:
  `results/01-ethernet-2026-11-03.md`.
- Fleet sample: 1.62 GB / 2.49 M pkts ≈ 653 B/pkt on `host-a`, consistent with
  frame bytes.
- MONAD prior art for `bytes_per_millisat`.
