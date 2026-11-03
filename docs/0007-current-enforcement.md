# 0007 — What a gate can enforce today, with zero patches

Status: Phase 0 exit document. Exp A settled by source inspection; Exp B measured
on `host-b`; Exp E blocked.

This is the table the rest of the roadmap depends on. If an entry is wrong, the
phase that relies on it is wrong.

## Summary

| Capability | Today | Mechanism | Gap |
|---|---|---|---|
| Refuse a peer at admission | **yes** | `peers.allow` / `peers.deny`, mtime-watched | up to ~1 tick (1 s) of staleness |
| Admit a peer at runtime | **yes** | same | same |
| Per-npub metering | **yes, aggregate** | `fipsctl show links` / `show peers` | per-frame-class split missing |
| Per-transport metering | **yes, aggregate** | `show transports`, `transport_type` | chargeable/non-chargeable split missing |
| Cut an established peer | **yes, but only durably with ACL deny** | `peers.deny` then `fipsctl disconnect` | a bare `disconnect` is undone by `auto_connect` in ~6.6 s |
| Pause one peer's forwarding, keep the link | **no upstream; yes with local patch (b)** | `set_forwarding` drop | patch is unmerged; sidecar integration pending |
| Price-aware parent selection | **no policy, but ACL-deny re-parents** | deny parent, disconnect | 109 ms re-parent, 1.6 s re-admit; no price signal (Exp H) |
| Frame-level gate on EtherType `0x2121` | **nft confirmed on `veth`; `ndsctl` unverified** | nft `netdev` + MAC set | Exp E / Phase 7 |
| Runtime admission without touching a file | **no** | ACL is file-based | patch (a) |

## Exp A — the counter boundary

**Question:** do FIPS counters count FMP frame bytes or payload bytes?

**Answer: FMP frame bytes.** Frame = `4`-byte common prefix + `12`-byte
remaining header + payload + `16`-byte AEAD tag. Medium encapsulation is
*outside* the counter.

Source evidence (0.6.0-dev tree, `f4a5b4a8e6`; fleet 0.5.3 behaves the same):

| Path | Call site | What is counted |
|---|---|---|
| UDP recv | `src/transport/udp/mod.rs:644,707` | `stats.record_recv(len)` where `len` is the `recvmsg` return — the UDP payload, i.e. the FMP frame |
| UDP send | `src/transport/udp/stats.rs` via `record_sent` | bytes actually written |
| Per-link send | `src/node/mod.rs:4592,4664` | `peer.link_stats_mut().record_sent(bytes_sent)` where `bytes_sent` is the sealed `wire_packet` |
| Ethernet recv | `src/transport/ethernet/mod.rs:1275` | `record_recv(len)` **before** the 3-byte FIPS frame header is stripped; includes that header, excludes the 14-byte Ethernet MAC header (SOCK_DGRAM) |
| TCP recv | `src/transport/tcp/mod.rs:1532` | `record_recv(data.len())` |
| Stats definition | `core/src/transport/types.rs:282–310` | `bytes_sent` / `bytes_recv` counters |

Fleet sample from `host-a`: `bytes_recv` 1.62 GB over 2.49 M packets ≈ **653 B per
packet**, consistent with full-size FMP frames, not payloads.

**Consequence for the spec:** a link session can use the daemon's own counters.
No re-counting is required. Encapsulation overhead is medium-specific and is not
in the counter; if a seller wants to recover it, it must be advertised
separately.

**Not done:** the planned packet-capture comparison on a lab node (compare
`show links` delta to `nft` counters for the same interval). Source inspection
is unambiguous; the capture is confirmation, not a blocker. It is still listed
in the Phase 0 checklist as an open item.

## Exp B — ACL reload latency

**Question:** how fast does a `peers.allow` / `peers.deny` change reach the
running daemon?

**Method:** append a throwaway npub (no private key held) to
`/etc/fips/peers.allow` on `host-b`, poll `fipsctl acl show` until it
appears in the *effective* allow set, restore the file, poll until it
disappears. Three runs, 20 ms poll interval. Backup and restore on every run;
file restored to 11 lines.

**Raw output:**

```
npub=npub1a8t6nuujdvkd8fe6zpq6yhnxk8p6susfq7y8aee3482hwlauyhgqyn56gn
run 1: add_ms=756 remove_ms=984
run 2: add_ms=960 remove_ms=978
run 3: add_ms=979 remove_ms=978
restored_lines=11
```

**Interpretation:** add 756–979 ms, remove 978–984 ms. The spread is the
phase of the 1 s node tick. The ACL reloader is driven from the tick loop
(`TICK = Duration::from_secs(1)`, `src/node/mod.rs:63`; `reload_peer_acl` in
`src/node/dataplane/rx_loop.rs`), so a change is applied on the next tick and
the worst case is one tick plus work.

**Consequences:**

1. The sidecar gate (Phase 1) can rely on file-based ACL changes taking effect
   within ~1 s. That is acceptable for admission of a new peer, and it is *not*
   acceptable for eviction of an active peer at exhaustion — a peer can push a
   lot of bytes in one tick.
2. Runtime admission via the control socket (patch (a)) is worth having for
   eviction latency alone, not only for convenience.
3. Any spec text that assumes sub-second admission MUST NOT be written until
   (a) exists.

## Exp C — cut and re-admit

**Question:** what does the only exhaustion lever cost, and does the cut hold?

**Method:** two-node UDP lab (`0.6.0-dev`, `2ba790b`), seller passive, buyer
`auto_connect`, strict ACL (`ALL` in `peers.deny`, buyer in `peers.allow`).
Run 1 did a bare `disconnect`; Run 2 did the durable sequence deny → wait for
the ACL → disconnect.

**Raw numbers:**

| Metric | Run 1 (bare disconnect) | Run 2 (durable) |
|---|---|---|
| ACL effective | 613 ms | 925–978 ms |
| Disconnect command | 46 ms | 49 ms |
| Link down observed | 777 ms | 764–2,142 ms |
| Auto reconnect | **6,756 ms**, new `link_id` | **6,616 ms**, new `link_id` |
| In-band ping after cut | fail | fail |
| In-band ping after reconnect | pass, no payment | pass, no payment |
| Durable hold | n/a | 3 s, no link |
| Re-admit | 3,950 ms | **2,701 ms** (829 ms ACL + 1,873 ms link) |

**Interpretation:** `fipsctl disconnect` alone is **not** eviction. With
`auto_connect` the peer re-establishes the link in 6.5–6.9 s (n=4), with a new
`link_id` and no new payment. The in-band path (and any payment that rides it) dies for
that window and then returns for free. A durable cut requires denying the npub,
waiting until `fipsctl acl show` reports the deny effective, and only then
disconnecting. Re-admission then costs 2.7–2.9 s (n=4). The sidecar was changed
to do exactly this; see
`results/C-2026-11-03-cut-readmit.md`.

**Still missing:** `grace`. Strict pause raises; the crude fallback is a durable
eviction, not a pause. Patch (b) remains the load-bearing change.

**Transport check:** the same cut/re-admit sequence over TCP gives a bare
reconnect of 7.7–7.9 s and re-admission of 2.8–3.6 s (n=4), against 6.5–6.9 s
and 2.7–2.9 s for UDP. The gate sequence is identical; TCP is about a second
slower to auto-reconnect. See `results/01-tcp-2026-11-03.md`.

## Patch (b) — per-peer transit policy

A local patch adds `Node.forwarding_blocked` and the control command
`set_forwarding {npub, allow}`. In an A–B–C chain, blocking A at B made A→C
fail while A→B and the A–B link stayed; allow restored A→C. That is the pause
shape: transit blocked, link and local path kept. The patch is unmerged and not
submitted; result `PB-2026-11-03-per-peer-forwarding.md`.

## Phase 1 demo — unpaid, pay, cut, re-admit

Two-node lab, real Nutshell ecash, payment out-of-band.

| Phase | Result |
|---|---|
| Link up, session `unpaid` | **14,274 bytes forwarded for 0 msat** |
| Real offline payment | 2 × 50 sat P2PK+DLEQ tokens accepted; replay refused |
| Paid traffic | 55,806 bytes; 5,806 msat overshoot (11.6 %, one step) |
| Durable evict | deny (786 ms) + disconnect (996 ms); ping fails |
| Prepaid re-admit | 677 ms ACL + 1,077 ms link = **≈1.75 s**; ping passes |

**Interpretation:** without patch (b), `unpaid` cannot be enforced: FIPS forwards
the peer's traffic while the session is unpaid. The only lever is a durable cut,
and re-admission costs a handshake. This is the Phase 1 exit evidence; see
`results/DEMO-2026-11-03-buyer-exhausts.md`.

## Exp H — ACL-deny and re-parenting

**Question:** can denying the current parent force a node onto its alternate
peer, and what does that cost?

**Method:** three-node triangle (`0.6.0-dev`, `2ba790b`), all directly peered;
`p` passive, `x` and `q` auto-connect. Strict ACLs on all three. The tree
settled as `x` root, `p` child of `x`, `q` child of `p`. Deny `q` on `p`, wait
for the ACL, disconnect, and watch `q`'s `is_parent` peer.

**Raw numbers:**

| Metric | Value |
|---|---|
| ACL deny on parent | 163 ms |
| Disconnect command | 51 ms |
| **Time to re-parent** | **109 ms** |
| Parent transitions | 1 (`p` → `x`) |
| Ping child→old parent before / after | pass / **pass** via `x` |
| Links before / after | 3 / 2 (`p`–`q` dropped) |
| Re-admit | 1,619 ms (454 ms ACL + 1,165 ms link) |
| Topology after re-admit | unchanged (`q` stays child of `x`) |

**Interpretation:** ACL-deny is a usable re-parenting lever when an alternate
peer is viable. The child moved in 109 ms with one transition, and the old
parent stayed reachable through the new path. The cost is one link (the tree
became a star at `x`), and re-admission does not revert the parent: parent
choice is sticky. That stickiness is the argument for patch (c) — a price change
needs an explicit re-evaluation, not just an ACL change. See
`results/H-2026-11-03-reparent.md`.

**Not tested:** a chain with no alternate peer (expected to split), price-driven
re-parenting, and Ethernet.

## Exp E — the captive portal (blocked)

**Question:** does `ndsctl` deauthorisation stop EtherType `0x2121` frames?

**Status: split.** The `ndsctl` half cannot run on the current fleet. Every
reachable node reports only `tcp` and `udp` transports (`fipsctl show
transports`); there is no Ethernet transport in the fleet, and `ndsctl` needs a
real AP with a captive portal.

The **nft half is done** (`results/E-nft-2026-11-03.md`). `harness/ethernet-lab/`
builds a `veth` pair in a container and checks an nft `netdev` ingress chain on
EtherType `0x2121` with an `ether_addr` set. All cases pass: empty set drops,
authorised MAC admits, removal drops again, an unauthorised source MAC drops,
and a non-`0x2121` EtherType is unaffected. A control rule on `0x0800` blocks
real IPv4/UDP delivery, which proves the hook is on the receive path.

One trap was found and recorded: AF_PACKET taps run before the ingress hook, so
a packet socket still sees frames nft has dropped. The test uses nft counters
for the `0x2121` verdict and UDP delivery for the control.

**What we can say now:** the nft rule shape is implementable and correct on
`veth`. The `ndsctl` hypothesis remains unconfirmed. The design in `0006`
therefore treats the frame gate as **rate control, not authorisation**, and does
not claim that a captive portal gates a FIPS link sale.

## What this means for the roadmap

- Phase 1 is viable: admit, meter, and evict all exist. The demo will be crude
  because eviction is the only lever.
- Phase 4 patch (b) is the one that changes the product, not a nice-to-have.
- Phase 7 must not be described as authorisation in any PR text.

## Reproduce

```sh
harness/scripts/acl-latency.sh host-b 3
harness/scripts/sample-counters.sh host-a 10
```

Record the version and rev with every run.
