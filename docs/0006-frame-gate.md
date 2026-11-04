# 0006 — The frame gate: physical, link, or neither

Status: the nft half is confirmed on `veth` (`results/E-nft-2026-11-03.md`),
throughput is measured (`results/E2-2026-11-03-frame-gate-throughput.md`), and
the per-MAC token bucket is compared across nft/tc/BPF
(`results/E4-2026-11-03-per-mac-token-bucket.md`). The `ndsctl` half is still
blocked on a real AP.

## The hypothesis

NoDogSplash / `ndsctl` gates **IP-family** traffic by MAC. It installs firewall
rules that match IPv4 and IPv6. FIPS over Ethernet uses EtherType `0x2121`,
which those rules do not match. If that is true, a client that is
"deauthorised" in the captive portal can still put FIPS frames on the link, and
a portal that believes it has gated the network has a side door.

Exp E is the test: deauthorise a client in `ndsctl`, then send FIPS Ethernet
frames from it and watch whether they cross.

## Why this matters for TollGate

If the portal does not gate FIPS frames, then the **captive portal is not a
physical gate** for a FIPS link sale. It is a gate for the browser, not for the
mesh. Two consequences:

1. A seller cannot rely on `ndsctl` to stop an unpaid client from using the
   link.
2. The frame gate has to be built separately, at a layer that matches
   `0x2121` — nft `netdev`, nft `bridge`, tc/eBPF, or 802.1X.

Conversely, if the portal *does* gate `0x2121` (for example because it drops
all non-IP traffic from unauthorised MACs), then it is a usable L0 gate and the
design should say so. Either answer changes the spec.

## Layers, and what each one actually authorises

| Layer | Mechanism | Sees | Authorises | Spoofable |
|---|---|---|---|---|
| Association | 802.11s / OWE / open SSID | device | may associate | no |
| Port | 802.1X, per-client VLAN, switch ACL | device / port | may emit frames at all | no |
| Frame | nft `netdev` / `bridge` on `ether type 0x2121` + MAC set | MAC, EtherType | may emit *FIPS* frames | **MAC — advisory** |
| Link (L1) | FMP msg1 → npub, ACL | npub, proven | may join the mesh | no |
| Transit (L2) | per-peer forwarding policy | npub + link | may use me as transit | no |

The frame gate is **rate and abuse control**. The npub gate is
**authorisation**. Do not let the former pretend to be the latter: a MAC is
spoofable, and on a shared medium an attacker who can emit `0x2121` frames can
also emit a msg1 with someone else's source MAC.

## The nft `netdev` sketch

```
table netdev tollgate {
  set authorised_macs { type ether_addr; }

  chain ingress {
    type filter hook ingress device "eth0" priority 0;
    ether type 0x2121 ether saddr @authorised_macs accept
    ether type 0x2121 drop
  }
}
```

Notes:

- `netdev` ingress runs before the bridge and before IP; it sees the EtherType.
- A per-MAC token bucket (`limit rate …`) is the rate-control part; it is not
  authentication.
- The set is populated by the gate module when a session reaches `paid` and
  removed at `evicted`. On a link with `deny_all` semantics the default is drop.
- This does not stop a spoofed MAC. It stops an unauthorised *device* from
  saturating the link with FIPS frames, and it gives the operator a lever that
  does not require the client to cooperate.

## The stronger options

| Option | What it gives | Cost |
|---|---|---|
| 802.1X / EAP-TLS | per-device port authorisation, not spoofable | RADIUS, supplicant, certs |
| OWE | encryption without a shared password; still association-level | client support |
| Per-client VLAN | isolation + policy per VLAN | switch config, one VLAN per client |
| 802.11s mesh peering | association is not authorisation; frames still flow | no |
| nft `netdev` + MAC set | EtherType-accurate, cheap, spoofable | kernel ≥ 4.10, nftables |

For a seller who controls the AP, 802.1X or per-client VLAN is the honest
physical gate. For a seller who does not, `netdev` is the best available and
must be labelled as rate control.

## Experiment register

- **E** — does `ndsctl` deauthorisation stop EtherType `0x2121`? *(blocked: fleet
  has UDP + TCP only; needs a real AP. The nft half is done.)*
- **E2** — nft `netdev` drop cost at 1k / 10k / 100k pps. Done: lossless at
  ~99k pps on `veth`; CPU comparison inconclusive.
- **E3** — does 802.11s association alone pass frames?
- **E4** — per-MAC token bucket: nft vs tc/BPF. Done: all three are per-MAC and
  identical in effect; nft is the smallest implementation
  (`results/E4-2026-11-03-per-mac-token-bucket.md`).

`harness/ethernet-lab/` now builds a `veth` pair and runs the nft rule, set and
verdict checks: all pass. That confirms the rule shape below is implementable.
It does **not** answer the `ndsctl` question, and it is not a throughput test.
A real AP is still needed for E and E3.

Methodological note for anyone repeating this: AF_PACKET taps run **before**
the netdev ingress hook, so a packet socket sees frames nft already dropped. Use
nft counters for the `0x2121` verdict, and a handled EtherType (IPv4/UDP) to
prove real delivery.

## What we will write in the spec

Not "the frame gate authorises clients". Instead:

> A link seller MAY operate a frame-level gate that drops EtherType `0x2121`
> frames from MAC addresses that are not associated with a `paid` session.
> This gate is rate and abuse control. It is not authorisation: MAC addresses
> are spoofable. Authorisation is the FMP link gate, which keys on the proven
> npub. Implementations MUST NOT treat frame-gate admission as payment.

## Throughput (E2)

An nft `netdev` ingress rule on EtherType `0x2121` was lossless at 1k, 10k and
~99k pps with 64-byte frames on a veth pair (the counter matched the sender to
0.01 %). Host-wide CPU (4–8 %) is dominated by the sender and does not
distinguish the hook from a userspace reader. `results/E2-2026-11-03-frame-gate-throughput.md`.

## Rate control (E4)

A per-MAC token bucket is the rate-control half of the gate. Three
implementations were compared on a bridged veth pair with three concurrent
senders (500 pps, 5,000 pps, 5,000 pps) and a 1,000 pps / 100-frame bucket:

```nft
set bucket { type ether_addr; flags dynamic; size 65535; timeout 10m; }

ether type 0x2121 update @bucket { ether saddr limit rate over 1000/second burst 100 packets } counter drop
ether type 0x2121 counter accept
```

All three implementations limited each over-rate MAC to ~1,000 pps and left
the under-rate MAC untouched, 3/3. The difference is operational:

| | nft | tc `police` | tc/BPF |
|---|---|---|---|
| Rule/state shape | 1 rule + dynamic set | 1 filter per MAC | 1 program + LRU map |
| Data-plane provisioning | automatic, first excess | control-plane per client | automatic |
| Bucket unit | packets | bytes (50 B of a 64 B frame) | packets |
| Privilege | `NET_ADMIN` | `NET_ADMIN` | `CAP_BPF` + `CAP_PERFMON` (+ `SYS_ADMIN` here) |
| Per-MAC counters | no (global rule counter) | per filter | needs a map reader |

The nft dynamic set materialises an element for **every sender** on its first
frame; the under-rate sender keeps an element but is never dropped. The element
carries that sender's token state, so its presence means "seen", not "over the
limit". A timeout bounds idle state.

For the frame gate, nft is the recommendation: smallest rule set, no extra
privilege, and the same `0x2121` match as the MAC-set sketch above. tc/BPF is
the option if the gate needs per-MAC counters, marks or actions beyond drop.
tc `police` is not the right primitive for many clients: one filter per client
and byte-based accounting.

Still rate control, not authorisation: a spoofed MAC can steal or exhaust a
bucket, and none of this admits a peer to the FMP mesh.
