# 03 — Ethernet

**Question:** can a link session be sold over the Ethernet transport, with the
beacon advertisement and a frame gate, and does the gate reconcile the same way
as TCP?

**Status:** done. Beacon discovery, metering, runtime admission and pause on a
dual-homed chain. See `../../results/01-ethernet-2026-11-03.md` and
`../../results/PE-2026-11-03-pause-ethernet.md`.

## Topology

Option A — `veth` pair (no hardware, enough for the nft and FMP parts):

```
netns seller ── veth ── netns buyer
   fipsd eth0            fipsd eth0
```

Option B — real AP + two stations (needed for `ndsctl` and 802.11s):

```
AP (captive portal) ── station A (seller) ── station B (buyer)
```

## Why it matters

- Ethernet is the transport where the "physical gate" question is real:
  EtherType `0x2121` is not IP, so a captive portal may not gate it. See
  `docs/0006-frame-gate.md`.
- It is the only transport with a beacon, so it is the only one where the
  endpoint advertisement (P1) has to describe a non-IP address.
- The FIPS receive counter includes the 3-byte FIPS frame header and excludes
  the 14-byte MAC header (`src/transport/ethernet/mod.rs:1275`). This is the
  transport where the counter boundary is easiest to mis-state.

## Steps

1. Create the pair (veth or AP).
2. Start `fipsd` with the Ethernet transport on both sides.
3. Confirm the beacon and the link handshake.
4. Advertise `["endpoint","ethernet","<mac-or-iface>"]`.
5. Run the shared acceptance test.
6. Record the receive counter against a known frame count, and state exactly
   which bytes it includes.
7. If the AP has a captive portal: deauthorise the buyer in `ndsctl`, keep
   sending `0x2121` frames, and record whether they cross. This is **Exp E**.

## Pass criteria

- [ ] Link up over Ethernet, session reaches all four states.
- [ ] Counter equals FMP frame bytes including the 3-byte FIPS header, excluding
      the 14-byte MAC header.
- [ ] Endpoint advertisement works without a port.
- [ ] Exp E has a yes/no answer with raw output.

## Exp E note

`veth` answers the nft question but not the `ndsctl` question. The nft half is
already done in `harness/ethernet-lab/` (`results/E-nft-2026-11-03.md`): the
rule matches `0x2121`, the MAC set admits and revokes, and a `0x0800` control
proves the hook blocks real delivery. If no AP is available, record the
`ndsctl` half as blocked and do not report the veth result as a captive-portal
result.
