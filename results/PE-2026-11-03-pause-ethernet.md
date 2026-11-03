# Result: PE — pause over a dual-homed Ethernet chain

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** PE — per-peer forwarding policy over Ethernet
- **Node(s):** `lt-ethc-a`, `lt-ethc-b`, `lt-ethc-c`
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local patch (b)
- **TollGate commit:** n/a
- **Repo commit:** Ethernet chain commit
- **Status:** pass, n=3

## Question

PB proved the pause shape on UDP: transit from a blocked peer is dropped while
its link and local path stay. Does the same hold over Ethernet, where the
transit node is dual-homed and A/C have no direct L2 path?

## Setup

```text
        left bridge            right bridge
  A ---- (eth0) B (eth1) ---- C
```

- A: one Ethernet transport on `left`.
- B: two named Ethernet instances, `left` (eth0) and `right` (eth1).
- C: one Ethernet transport on `right`.
- All beacon-enabled with `auto_connect`; no static peer entries.

The only A→C path is through B. B runs the patched image, so
`fipsctl set-forwarding <A> block|allow` is available on its own CLI.

```sh
harness/exp-eth-chain/run-pause-eth.sh
```

## Measurements

| Run | A–B link | B–C link | Baseline A→C | Block: A→C | Block: A→B | A–B link preserved | Dropped (A) | Allow: A→C |
|---|---|---|---|---|---|---|---|---|
| 1 | 832 ms | 499 ms | pass | **fail** | pass | yes | 12 pkts / 1,683 B | pass |
| 2 | 1,593 ms | 118 ms | pass | **fail** | pass | yes | 13 pkts / 1,818 B | pass |
| 3 | 1,541 ms | 117 ms | pass | **fail** | pass | yes | 15 pkts / 2,068 B | pass |

| Metric | Range (n=3) |
|---|---|
| A–B discovery | 832–1,593 ms |
| B–C discovery | 117–499 ms |
| Transit blocked by `set-forwarding` | 3/3 |
| A→B (local delivery) preserved | 3/3 |
| A–B link id preserved across block | 3/3 |
| Per-peer attribution | 12–15 packets / 1,683–2,068 bytes |
| Allow restores A→C | 3/3 |

Note: the A–B link id can churn during startup discovery (one run started at 1
and was 2 by the baseline). The comparison above is the id immediately **before**
the block, not the startup id.

## Interpretation

1. **The pause shape is transport-independent.** Blocking transit at a
   dual-homed Ethernet node stops A→C while A→B keeps working and the A–B link
   is preserved. No disconnect is issued.
2. **The policy is per peer, not per transport.** A is blocked on the `left`
   instance only because that is where its traffic arrives; C is unaffected.
   The node-wide counters and per-peer attribution work unchanged.
3. **Discovery churn is a setup detail.** Ethernet beacons can re-establish a
   link during startup, changing the link id. Compare the id around the block,
   not from container start. This is the same lesson as PD.
4. **This closes the Ethernet half of Phase 2.** TCP has cut/re-admit; Ethernet
   now has discovery, metering, admission and pause. BLE and Tor remain.

## Caveats

- Docker bridges, not a real switch; dual-homing is two bridges, not two VLANs.
- `set-forwarding` was called through the patched CLI on B; the sidecar
  `FipsGate.pause()` path was validated on UDP (PB), not re-run here.
- One topology, three runs, no payment traffic.
- The beacon interval is 10 s; longer intervals will lengthen re-admission.

## Follow-ups

- [ ] Run the full payment capstone (PD) over this chain.
- [ ] Real switch and mixed Ethernet↔UDP paths.
- [ ] BLE (`mark_verified`) and Tor.

## Artefacts

- `harness/exp-eth-chain/` (compose, A/B/C configs, orchestrator, runner)
- `results/01-ethernet-2026-11-03.md` (two-node discovery/metering)
