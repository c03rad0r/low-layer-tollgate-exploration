# Result: E4 — per-MAC token bucket, nft vs tc-police vs tc/BPF

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** E4 — can each source MAC be rate-limited independently, and
  how do nft, tc `police`, and a tc/BPF classifier compare?
- **Node(s):** local T14; Alpine 3.20 container with three veth pairs and a
  bridge
- **Kernel:** host 7.0.0-42-generic; nftables 1.0.9; iproute2 6.9.0
- **FIPS version / rev:** n/a (no `fipsd`)
- **Repo commit:** E4 commit
- **Status:** pass, n=3, all three modes

## Question

The frame gate can drop `0x2121` and honour a MAC set. That is binary admission
for a *spoofable* identifier. Before wiring it into the link module, can it also
rate-limit each MAC independently, so one abuser cannot consume the shared
allowance? And is nft the right place, or does tc/eBPF buy something?

The failure this test looks for is a **global** bucket: one token bucket shared
by all senders. It passes a naive single-client test but throttles the well-
behaved client as soon as anyone floods.

## Setup

Topology (a bridge is used so the receiver sees only frames that survived the
gate; AF_PACKET taps on the gate interface itself see pre-hook traffic, which
is the trap recorded in `results/E-nft-2026-11-03.md`):

```text
                        gate ingress on s1
  s0 (sender) == s1 == br0 == d0 == d1 (receiver, AF_PACKET)
```

Three senders run concurrently, each with its own source MAC:

| Sender | Offered rate | Role |
|---|---|---|
| A `02:00:00:00:00:0a` | 500 pps | under the bucket |
| B `02:00:00:00:00:0b` | 5,000 pps | over the bucket |
| C `02:00:00:00:00:0c` | 5,000 pps | over the bucket |

Bucket: **1,000 pps, burst 100 frames**, 64-byte frames, 3 s per run.

Modes:

1. **none** — control, no gate. All frames should arrive.
2. **nft** — `netdev` ingress on `s1`:

   ```
   set bucket { type ether_addr; flags dynamic; size 65535; timeout 10m; }
   ether type 0x2121 update @bucket { ether saddr limit rate over 1000/second burst 100 packets } counter drop
   ether type 0x2121 counter accept
   ```

   The `limit rate over` expression is evaluated **per set element**, so the
   bucket is per MAC. Only MACs that exceed the rate get an element.

3. **tc** — `clsact` on `s1`, one `flower` filter per source MAC:

   ```
   tc filter add dev s1 ingress protocol 0x2121 flower src_mac <MAC> \
     action police rate 400kbit burst 5k drop
   ```

4. **bpf** — `clsact` + `token-bucket.o`, one `LRU_HASH` map keyed by source MAC
   with `{tokens, last_ns, remainder}` per entry.

```sh
harness/ethernet-lab/run-token-bucket.sh 3
```

## Raw measurements

Frames received by the bridge-side receiver, per source MAC.

| Mode | Run | Sent A/B/C | Received A/B/C | Loss A/B/C |
|---|---|---|---|---|
| none | 1–3 | 1,500 / 15,000 / 15,000 | 1,500 / 15,000 / 15,000 | 0 / 0 / 0 |
| nft | 1–3 | 1,500 / 15,000 / 15,000 | **1,500 / 3,099 / 3,099** | 0 / 79.3 % / 79.3 % |
| tc | 1–3 | 1,500 / 15,000 / 15,000 | **1,500 / 3,101 / 3,101** | 0 / 79.3 % / 79.3 % |
| bpf | 1–3 | 1,500 / 15,000 / 15,000 | **1,500 / 3,099 / 3,099** | 0 / 79.3 % / 79.3 % |

The three gated modes are identical to the frame and deterministic across all
nine gated runs.

Delivered rate for B and C, including the initial burst:

```text
(3,099 - 100) / 3 s ≈ 1,000 pps      nft, bpf
(3,101 - 100) / 3 s ≈ 1,000 pps      tc
```

A was never touched: 1,500 sent, 1,500 received, in every gated run.

### State after traffic (nft)

```
set bucket {
    type ether_addr
    size 65535
    flags dynamic,timeout
    timeout 10m
    elements = { 02:00:00:00:00:0b limit rate over 1000/second burst 100 packets,
                 02:00:00:00:00:0c limit rate over 1000/second burst 100 packets }
}
```

A (500 pps, under the rate) has **no element**: the dynamic set only
materialises MACs that are over the limit. Idle elements expire on the 10 min
timeout.

### State after traffic (tc)

```
src_mac 02:00:00:00:00:0b
  police 0x2 rate 400Kbit burst 5Kb mtu 2Kb action drop
  Sent 750000 bytes 15000 pkt (dropped 11899, overlimits 11899)
```

One filter per MAC. B's filter reports 15,000 seen, 11,899 dropped, 3,101
passed. The filter for A exists but saw 0 packets in this run because A was
not sending in the tc state capture.

## Interpretation

1. **All three are per-MAC.** B and C each received their own ~1,000 pps
   allowance; they did not share one. A was untouched. A global bucket would
   have throttled A and/or halved B and C, so the test discriminates the
   property it claims to measure.
2. **nft is the smallest implementation.** One rule plus a dynamic set, state
   created by the data plane on first excess, and no per-client control-plane
   call. The set only holds over-limit MACs, and a timeout bounds it.
3. **tc `police` is byte-based, not packet-based.** It accounted ~50 bytes of
   each 64-byte frame (it excludes the 14-byte MAC header), so the nominal
   512 kbit/s setting delivered ~1,334 pps, not 1,000. Calibrating to
   **400 kbit/s** (50 B × 8 × 1,000) gave the same 1,000 pps as nft. A
   deployment with variable frame sizes must size the bucket in bytes, not
   pps, or it will not be fair.
4. **tc needs a filter per client.** 3 MACs → 3 filters; 1,000 clients → 1,000
   filters and 1,000 control-plane operations. nft's dynamic set and the BPF
   map are O(1) rules with per-key state.
5. **BPF is the most flexible but needs more privilege and a control plane.**
   Attaching the tc/BPF classifier failed with only `NET_ADMIN`; it needed
   `CAP_BPF`, `CAP_PERFMON` and `CAP_SYS_ADMIN` on this host
   (`kernel.unprivileged_bpf_disabled=2`). Per-MAC drop counters and
   revocation are not free: they need a map-dump tool or a second program.
6. **Methodology fixes recorded** (all were silent wrong results first):
   - BTF-defined maps did not relocate under the image's tc/libbpf pair; the
     map fd arrived as 0 and the verifier rejected the lookup as
     `scalar expected=map_ptr`. The legacy `maps` section loads.
   - Refilling in whole milliseconds halved the delivered rate at a 1 ms
     cadence (500/1,000 frames passed instead of ~3,000). Carrying a
     sub-token remainder fixed it.
   - The sender's burst pacer rounded sub-1 kpps rates up to 1 kpps; the low-
     rate path now uses a 1e9/pps tick.

## Recommendation

For the Phase 7 frame gate, use **nft** for the per-MAC rate limit:

- it is the smallest rule set and needs only `NET_ADMIN`;
- it matches the existing `0x2121` + MAC-set sketch in `docs/0006`;
- the dynamic set auto-provisions and can be bounded with `timeout`.

Use tc/BPF only if the gate needs per-MAC **counters, marks or actions** beyond
drop. tc `police` is not the right primitive for many clients because of the
per-MAC filter requirement and byte-based accounting.

The frame gate remains rate/abuse control, not authorisation. A spoofed MAC can
evade or steal a bucket; the FMP link gate keyed on the proven npub remains the
authorisation boundary.

## Caveats

- 64-byte frames, fixed rates, one host, one veth/bridge path. Real Wi-Fi has
  airtime contention, aggregation and per-frame costs not modelled here.
- The bucket is 1,000 pps/100 frames for all three modes; tc's equivalent is a
  calibrated byte rate (400 kbit/s), which is only equivalent at this frame
  size.
- nft has a **global** drop counter, not per-MAC counters. Per-MAC accounting
  would need `counter` on set elements or a separate rule/set design; tc and
  BPF have it per filter/map but need a reader.
- The BPF map was not dumped; per-MAC token state is inferred from the
  received counts, not read back.
- No real AP, no `ndsctl`, no spoofing, no client churn. Exp E3 remains open.

## Follow-ups

- [ ] Per-MAC counters for nft (element counters or a paired set).
- [ ] Provisioning-cost comparison for 1,000 MACs (tc filters vs nft elements).
- [ ] Real AP: combine this with the `ndsctl` question (Exp E).
- [ ] Wire the nft rule to session state in Phase 7 (`set_addition` /
      `set_removal` alongside the MAC set).
- [ ] Try `tc` `police` with `pkts`-based units if iproute2 adds them, to avoid
      the byte calibration.

## Artefacts

- `harness/ethernet-lab/token-bucket-test.py`
- `harness/ethernet-lab/token-bucket.bpf.c`
- `harness/ethernet-lab/Dockerfile.ebpf`
- `harness/ethernet-lab/run-token-bucket.sh`
- `harness/ethernet-lab/bench.c` (`send` with source MAC, `recvmac`)
