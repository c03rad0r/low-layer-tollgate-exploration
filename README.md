# low-layer-tollgate-exploration

Can a TollGate be sold at the **link** layer of FIPS — per-transport,
per-neighbour peering and transit — rather than only at the service layer?

This repo holds the experiments, the notes, and the spec drafts. It is not a
product repo. Nothing here is merged upstream, and nothing here runs on
mainnet funds.

## The short version

FIPS transports are deliberately identity-blind: they move bytes between
transport addresses, and the mapping from address to npub happens at the link
layer after a Noise IK handshake. So "a TollGate inside the transport driver"
cannot know who is paying. The useful design is a gate at one of three seams,
with **per-transport meaning policy scope, not code placement**:

| Seam | Sees | Can decide |
|---|---|---|
| **L0** transport / nft `netdev` / tc | transport, address, bytes | rate caps, flood shield, may this device emit frames |
| **L1** link admission (after msg1 DH) | npub, proven | admit, deny, credit, per-npub limit |
| **L2** established link data plane | npub + link + counters | meter, pause transit, renew |

Today FIPS gives us L1 and L2 only as *admit* or *disconnect*. It cannot pause
one peer's forwarding while keeping the link. That gap is the load-bearing one,
and the Phase 1 demo is designed to fail on it so the evidence exists.

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Seams: counter boundary (A), ACL latency (B), captive-portal bypass (E) | **A, B done; E nft half done, ndsctl blocked** |
| 1 | Sidecar gate over the control socket, zero FIPS changes (C, H) | **C, H and real-payment demo done; pause still missing** |
| 2 | TCP, Ethernet, BLE, Tor demos behind one gate interface | TCP cut/re-admit done; others pending |
| 3 | Local mint + receiver spent journal (F, G) | mint + offline verify + durable replay; session/Exp G pending |
| 4 | FIPS patches (a) runtime admission, (b) per-peer forwarding, (c) price in `link_cost` | (b) local patch, per-peer counters, 3/3 UDP + 3/3 TCP capstone; (a)/(c) pending |
| 5 | Spec PRs to `OpenTollGate/tollgate` (P1–P4) | drafts updated with PB/PD evidence; no PRs opened |
| 6 | Channels (`cdk-spilman`) and treasury swaps (Granola) | not started |
| 7 | Frame gate: nft `netdev` on `ether type 0x2121` (E2–E4) | nft correctness confirmed; rate/AP tests pending |

## Read this first

- `AGENTS.md` — how we work, including the upstream interaction policy.
- `docs/0001-three-seams.md` — the framing everything else depends on.
- `docs/0002-metering-boundary.md` — what a byte is, and why.
- `docs/0008-gate-interface.md` — the five verbs the sidecar exposes.
- `docs/0009-nullifier-journal.md` — the durable replay record.
- `docs/0010-exposure-cap.md` — the bound on cross-seller double spend.
- `docs/0011-payment-gate.md` — verifier → exposure → journal ordering.
- `ROADMAP.md` — phases and exit criteria.
- `CHECKLIST.md` — live tracker.

## Layout

```
docs/          design notes, numbered
spec-drafts/   ready-to-PR text for OpenTollGate/tollgate
experiments/   one directory per experiment
harness/       lab topology, scripts, compose file
patches/       local unmerged FIPS patches
results/       one file per run; raw output first
```

## Running things

Fleet experiments are read-only unless the experiment says otherwise, and are
run through the operator's SSH config. Lab experiments use `harness/`.

```sh
# read-only counter sample from a fleet node
harness/scripts/sample-counters.sh host-a 10

# ACL reload latency (writes a throwaway npub, restores the file)
harness/scripts/acl-latency.sh host-b
```

## Licence

MIT. See `LICENSE`.
