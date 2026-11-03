# Result: E2 — frame-gate throughput, nft netdev vs userspace

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** E2 — can an nft `netdev` frame gate keep up at 1k/10k/100k pps,
  and does it cost less CPU than a userspace reader?
- **Node(s):** local T14; Alpine 3.20 container on a veth pair
- **Kernel:** host 7.0.0-42-generic, nftables 1.0.9
- **FIPS version / rev:** n/a (no `fipsd`)
- **Repo commit:** throughput commit
- **Status:** pass for drop correctness/throughput at the tested rates; CPU
  comparison inconclusive

## Question

The frame gate (Exp E) drops EtherType `0x2121` correctly at low rates. Before
recommending it, does the nft `netdev` hook keep up at 1k, 10k and 100k pps, and
is it cheaper than reading and dropping in userspace?

## Setup

```sh
harness/ethernet-lab/run-throughput.sh          # 1k,10k,100k for 2 s each
```

Inside an Alpine container with `NET_ADMIN` + `NET_RAW` and `--network none`:

- veth pair `fg0` ↔ `fg1`;
- `bench` (C, AF_PACKET) sends 64-byte frames with EtherType `0x2121`, paced in
  1 ms bursts, on `fg1`;
- ingress is on `fg0`;
- three modes:
  - **nft drop** — `ether type 0x2121 counter drop`;
  - **nft accept** — same rule with `counter accept`;
  - **userspace** — no table; a C receiver reads frames from `fg0`.

Each mode/rate sends for 2 s. `seen` is the nft counter delta or the receiver
count; `busy%` is the host-wide non-idle CPU delta over the window (all CPUs).

## Raw measurements

| Mode | Target pps | Sent (pps) | Seen (pps) | Loss | Host busy |
|---|---|---|---|---|---|
| nft drop | 1,000 | 2,000 (987) | 2,000 (987) | 0 | 5.0 % |
| nft drop | 10,000 | 20,000 (9,904) | 20,000 (9,906) | 0 | 4.5 % |
| nft drop | 100,000 | 200,000 (98,819) | 200,000 (98,814) | 0 | 4.2 % |
| nft accept | 1,000 | 2,000 (986) | 2,000 (986) | 0 | 4.7 % |
| nft accept | 10,000 | 20,000 (9,845) | 20,000 (9,843) | 0 | 6.1 % |
| nft accept | 100,000 | 200,000 (98,296) | 200,000 (98,280) | 0 | 5.2 % |
| userspace | 1,000 | 2,000 (985) | 2,002 (986) | 0 | 7.6 % |
| userspace | 10,000 | 20,000 (9,845) | 20,000 (9,845) | 0 | 6.6 % |
| userspace | 100,000 | 200,000 (98,667) | 200,000 (98,667) | 0 | 5.3 % |

## Interpretation

1. **The nft `netdev` gate is lossless at every tested rate.** The counter
   matched the sender to within 0.01 % at ~99k pps for both drop and accept.
2. **No CPU advantage is measurable at this scale.** Host-wide busy was 4–8 %
   in every mode, dominated by the sender and the veth path; the differences are
   inside run-to-run noise. This benchmark cannot show nft is cheaper than
   userspace, only that it is not slower.
3. **~99k pps is a tested point, not a ceiling.** The sender reached the 100k
   target; the gate kept up. Higher rates need a multi-queue sender or a
   hardware NIC to be meaningful.
4. **The measurement is end-to-end and blunt.** `busy%` includes the sender and
   both veth ends. A per-CPU softirq breakdown would be needed to compare the
   hook cost itself.
5. **Methodology note:** the first version paced per frame with `nanosleep`,
   which capped the sender at ~31k pps and made the 100k row meaningless. The
   final version paces in 1 ms bursts; the 100k row above is the real target.

## Caveats

- 64-byte frames, one veth pair, one queue, one host. Real Ethernet and Wi-Fi
  have different per-frame costs.
- Host-wide CPU is too coarse to price the hook; treat the CPU columns as
  "no regression", not as a comparison.
- The userspace mode drops nothing: it reads every frame, which is not what a
  gate would do with unauthorised traffic. It is an upper bound on reading cost.
- No per-MAC token bucket (E4) and no `ndsctl` on a real AP (E3).

## Follow-ups

- [ ] Per-CPU softirq/ksoftirqd accounting for the hook cost.
- [ ] Multi-queue sender (or `pktgen`) to find the actual ceiling.
- [ ] E4: nft per-MAC token bucket vs tc/eBPF.
- [ ] Repeat on a real NIC and a Wi-Fi AP.

## Artefacts

- `harness/ethernet-lab/bench.c`
- `harness/ethernet-lab/throughput-test.py`
- `harness/ethernet-lab/Dockerfile.bench`, `run-throughput.sh`
