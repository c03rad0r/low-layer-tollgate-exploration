# TIP: Frame-level rate control for FIPS links (not authorisation)

- **Target repo:** `OpenTollGate/tollgate`
- **Status:** Draft for PR
- **Depends on:** P1 (endpoint advertisement), P3 (wire-byte metering)
- **Experiment citations:** E-nft (`results/E-nft-2026-11-03.md`),
  E2 (`results/E2-2026-11-03-frame-gate-throughput.md`),
  E4 (`results/E4-2026-11-03-per-mac-token-bucket.md`),
  `docs/0006-frame-gate.md`

## Abstract

FIPS over Ethernet carries FMP inside EtherType `0x2121`. Before an FMP
handshake, there is no proven npub to authorise on, so a seller that controls
the L2 segment can only see a MAC address. This document defines what such a
**frame gate** may and may not do:

- it MAY drop or rate-limit `0x2121` frames per source MAC;
- it MUST NOT be treated as payment, admission or identity;
- it MUST NOT be used to charge for frames it dropped;
- it MUST NOT break the path a new client needs in order to pay.

The normative authorisation boundary remains the FMP link gate keyed on the
proven npub.

## Motivation

A seller on a shared L2 segment (Wi-Fi AP, bridge, switch port) has three
problems the link gate cannot solve, because they happen before or below FMP:

1. **Unknown devices.** A device that never completes a handshake can still
   emit `0x2121` frames and consume airtime or uplink.
2. **Flooding.** A known or unknown MAC can saturate the segment; the link
   gate only sees an established link's FMP traffic.
3. **Spoofing.** A MAC is not an identity, but it is the only selector visible
   before `msg1`.

Captive portals do not necessarily solve this: `ndsctl` installs IP-family
rules, while FIPS uses a non-IP EtherType. Whether a given portal drops
`0x2121` is implementation-specific and unverified here (Exp E's `ndsctl` half
is blocked on a real AP). A protocol cannot assume the portal gates FIPS
frames.

At the same time, a frame gate is dangerous if it is mistaken for
authorisation. It is trivial to spoof a MAC, and dropping unknown MACs can
lock a paying customer out of the very path they need to reach checkout. The
protocol needs to say both what the gate is for and where it must stop.

## Specification

### 1. Terms

- **Frame gate** — an L0/L2 mechanism that inspects Ethernet frames and
  applies a verdict (pass, drop, rate-limit) before FMP is parsed.
- **Gate MAC** — the source MAC observed on a frame, as seen by the seller's
  ingress hook.
- **Session MAC** — the source MAC observed during a successful FMP handshake
  on the Ethernet transport, bound to the session's npub for the session's
  lifetime.
- **Authorised set** — gate MACs the seller currently admits. Advisory only.

### 2. The gate is rate control, not authorisation

A frame gate MUST NOT be used as:

- proof of payment;
- proof of identity;
- the sole basis for admitting a peer to the FMP mesh;
- a reason to skip the FMP link gate.

A seller MAY use it for:

- dropping or rate-limiting `0x2121` frames from MACs with no session;
- bounding a single MAC's share of the segment;
- protecting the seller's uplink and airtime from a flood;
- enforcing a per-device fair-use ceiling alongside the per-session meter.

These are abuse controls. They do not create a session, credit a balance, or
change a session state.

### 3. First contact and the checkout path

A gate that default-drops unknown MACs MUST NOT be the only path to payment.
The seller MUST provide at least one of:

1. a checkout path outside the gated EtherType (captive portal, HTTPS, QR,
   out-of-band invoice); or
2. a low-rate admission lane for `0x2121` handshake traffic from unknown MACs,
   sufficient to complete `msg1` and the payment exchange.

A seller MUST NOT drop the frames of a session that is in `unpaid` or `grace`
at L0. Those states are defined at L1/L2: the link stays up and transit is
paused (`P4`). Dropping at L0 would destroy the link and with it the evidence
needed to resume. L0 drop is for devices that are not peers, or for `evicted`
sessions after the durable eviction completes.

### 4. Per-MAC rate limiting

If a seller rate-limits, it SHOULD use an independent token bucket per gate MAC.

- The bucket MUST be per MAC, not global. A global bucket lets one sender
  consume the allowance of every other sender.
- The seller SHOULD express the bucket in **frames per second** when frame
  sizes are uniform, and in **bytes per second** when they are not. A
  bytes-based bucket calibrated for one frame size is not fair across sizes.
- The seller SHOULD allow a bounded burst; a bucket with no burst penalises
  legitimate on/off traffic.
- Bucket state MUST be bounded: a size cap and an idle timeout for per-MAC
  state. Unbounded state is a memory-exhaustion vector.
- The bucket MAY be stricter for MACs with no session than for MACs bound to a
  `paid` session.

The reference parameters are not normative: the E4 lab used 1,000 pps and a
100-frame burst for a 64-byte frame.

### 5. Charging

Frames dropped or delayed by the frame gate are **not chargeable**. They
deliver no service and must not appear in the metered byte count (`P3`).

If the gate is implemented outside the FMP transport, the seller MUST subtract
the gate's drop delta from the session's chargeable bytes for the same window,
exactly as it subtracts forwarding-policy drops for a paused peer. Double
counting a dropped frame is a billing defect.

The frame gate MUST NOT credit a session. Only a verified payment does that.

### 6. Session binding

On Ethernet, the seller SHOULD learn the session MAC from the `msg1` frame's
L2 source and bind it to the session npub for the session lifetime.

- The binding MUST be refreshed from a new handshake, not from unsolicited
  frames claiming the same MAC.
- A gate MAC that later completes a handshake is the same device only if the
  seller observed it; the protocol does not require trusting prior frames.
- A seller that cannot observe the source MAC (UDP, TCP, Tor, BLE) MUST NOT
  pretend to have a frame gate for that transport. The gate is an Ethernet/L2
  facility, not a universal one.

### 7. State and observability

The seller SHOULD expose, per gate MAC:

- frames and bytes passed and dropped;
- current bucket state or an equivalent summary;
- the session npub bound to the MAC, if any.

Counters MUST NOT be attributed to an npub without a handshake-derived
binding; a spoofed MAC would otherwise let an attacker inflate or exhaust
another payer's accounting.

### 8. Media and EtherType

This document applies to media where the seller can match the FIPS EtherType
before IP:

- Ethernet (`0x2121`), including bridged and 802.11s paths;
- equivalent L2 transports that expose an EtherType.

It does not apply to UDP, TCP, Tor or BLE, where the seller cannot key on a
pre-FMP frame. Those transports rely on the FMP link gate alone.

## Rationale

The alternative mechanisms are stronger but heavier:

| Mechanism | Authorises | Cost |
|---|---|---|
| 802.1X / EAP-TLS | per-device port | RADIUS, certs, supplicant |
| Per-client VLAN | isolation | switch/AP config, one VLAN per client |
| 802.11s association | association only | does not gate frames |
| nft `netdev` + MAC set + per-MAC bucket | advisory rate control | kernel ≥ 4.10, `NET_ADMIN` |
| tc/BPF classifier | advisory rate control, richer actions | BPF privilege + control plane |
| Captive portal (`ndsctl`) | IP-family traffic | unverified for `0x2121` |

For a seller who controls the AP, 802.1X or per-client VLAN is the honest
physical gate. For a seller who does not, the frame gate is the best available
and must be labelled as rate control.

E4 measured three implementations of the same per-MAC bucket. nft (one rule +
a dynamic set) and tc/BPF (one program + an LRU map) produced identical
per-MAC behaviour; tc `police` required one filter per MAC and byte-based
calibration. nft is the smallest sufficient implementation.

## Backwards compatibility

- No FMP wire change. The gate operates below FMP.
- No new fields in session or payment messages.
- Sellers without an L2 gate are unaffected; the rules are opt-in.
- Buyers need no change. A buyer cannot tell whether a frame was dropped by a
  gate or lost on the medium; retransmission and the session deadline cover
  both.

## Security considerations

- **Spoofing.** An attacker can use another device's MAC and either steal its
  allowance or exhaust its bucket. Per-MAC limiting is fairness, not security.
- **Bucket DoS.** If the bucket is per MAC and MACs are spoofable, an attacker
  can force a victim's bucket to empty by sending as the victim. The gate MUST
  NOT use the bucket to deny the victim's *link*; it may only rate-limit.
- **State exhaustion.** Per-MAC state is attacker-controlled. Cap the number
  of entries and expire idle ones.
- **First-contact lockout.** A default-drop gate without an out-of-band
  checkout path is a self-DoS. See §3.
- **Charging.** Never bill dropped frames; never credit from gate state.
- **Privacy.** A MAC is a persistent device identifier. Sellers SHOULD NOT log
  it longer than needed for the session and abuse window.

## Open questions

1. Does a real captive portal (`ndsctl` or equivalent) drop `0x2121` when it
   deauthorises a client? Exp E's AP half is still open.
2. Should the session MAC be advertised by the seller as part of the session
   record, or learned locally? Local learning avoids a new wire field but is
   transport-specific.
3. Is a standard burst/rate profile useful, or should it remain a seller
   policy? The lab used 1,000 pps + 100 frames as a reference only.
4. Should `evicted` at L2 always imply an L0 drop, or only after the ACL write
   is durable? P4 says eviction is deny → wait → disconnect; L0 drop can
   follow the same ordering.

## Evidence

| Claim | Experiment |
|---|---|
| `0x2121` can be matched and dropped per MAC | E-nft: 11/11 cases pass |
| nft drop/accept is lossless to ~99k pps | E2: counter matches sender to 0.01 % |
| per-MAC bucket, independent per sender | E4: A untouched; B and C each ~1,000 pps, n=3 |
| nft, tc-police and tc/BPF agree | E4: 3,099 / 3,101 / 3,099 frames, n=3 |
| MACs are spoofable, so this is not auth | E-nft, `docs/0006` |
