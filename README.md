# low-layer-tollgate-exploration

Can a TollGate be sold at the **link** layer of FIPS — per-transport,
per-neighbour peering and transit — rather than only at the service layer?

This repo holds the experiments, the notes, and the spec drafts. It is not a
product repo. Nothing here is merged upstream, and nothing here runs on
mainnet funds.

## What is and is not here

This is the public evidence base for the five spec PRs. The unmerged FIPS
patches and the unsent out-of-band write-up are deliberately **not** in this
repository; they live in a private side repo, per `AGENTS.md`. The results
describe what the patches made measurable, not how they are implemented.

Fleet hostnames and lab identity seeds in the results and harness configs have
been replaced with placeholders (`host-a`, `gateway`,
`REPLACE_WITH_HEX_SEED`) before publication. Counts, timings and raw output are
otherwise unchanged; the original logs are available on request.

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

Upstream FIPS gives us L1 and L2 only as *admit* or *disconnect*. It cannot
pause one peer's forwarding while keeping the link. That gap is the load-bearing
one. The Phase 1 demo was built to fail on it, and patch (b) closes it locally:
one peer's transit is blocked while its link, Noise session and local path stay
(`results/PB-2026-11-03`, `results/PD-2026-11-03`). The patch is unmerged.

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Seams: counter boundary (A), ACL latency (B), captive-portal bypass (E) | **A, B done; E nft + E2 throughput done, ndsctl blocked** |
| 1 | Sidecar gate over the control socket, zero FIPS changes (C, H) | **C, H, real-payment demo and durable eviction/re-admit done; pause via local patch (b)** |
| 2 | TCP, Ethernet, BLE, Tor demos behind one gate interface | TCP + Ethernet done (incl. Ethernet pause); BLE/Tor pending |
| 3 | Local mint + receiver spent journal (F, G) | F, G, settlement, batching, drain + dead-letter/health done |
| 4 | FIPS patches (a) runtime admission, (b) per-peer forwarding, (c) price in `link_cost` | all three local patches + lab results |
| 5 | Spec PRs to `OpenTollGate/tollgate` (P1–P5) | **five discussion-draft PRs open: #51–#55** |
| 6 | Channels (`cdk-spilman`) and treasury swaps (Granola) | treasury boundary decided (out of gate path); channel not started |
| 7 | Frame gate: nft `netdev` on `ether type 0x2121` (E2–E4) | correctness + E2 throughput + E4 per-MAC bucket done; E3/ndsctl pending |
| 8 | Balloon decision experiments (BYPASS, SELECTOR, TWOKEY, CRASH, EXPIRY, OUTAGE, LORA, INTERMITTENT, BIND, FEATURES) | **initial measurements and decisions done in `docs/0019`; hardware/long-window follow-ups remain** |
| 9 | Production direction (account, strict offline P2PK, CRC journal) | **host-side prototypes and tests done; controller/hardware/release gates open in `docs/0020`** |
| 10 | App-relay request-path integration (`relay.py` + CRC adapter) | **verified host integration in `docs/0022`; real FIPS/mint/flight work open** |
| 11 | Live FIPS-local payment/relay app | **two-peer UDP sequence passes (`docs/0023`); peer watch, DLEQ, real RF/embedded work open** |

## Read this first

- `AGENTS.md` — how we work, including the upstream interaction policy.
- `docs/0001-three-seams.md` — the framing everything else depends on.
- `docs/0002-metering-boundary.md` — what a byte is, and why.
- `docs/0008-gate-interface.md` — the five verbs the sidecar exposes.
- `docs/0009-nullifier-journal.md` — the durable replay record.
- `docs/0010-exposure-cap.md` — the bound on cross-seller double spend.
- `docs/0011-payment-gate.md` — verifier → exposure → journal ordering.
- `docs/0012-runtime-admission.md` — runtime admission (patch a).
- `docs/0013-seller-controller.md` — the session→gate loop.
- `docs/0014-settlement.md` — redeem → SETTLED → exposure release.
- `docs/0015-token-vault.md` — persist the token before credit.
- `docs/0016-drain.md` — the background settlement loop.
- `docs/0017-frame-gate-module.md` — the L0 frame-gate module (nft).
- `docs/0018-treasury-plane.md` — why cross-mint swaps stay off the gate path.
- `docs/0019-balloon-decision-experiments.md` — balloon decisions, experiments
  and tracking checklist.
- `docs/0020-balloon-production-readiness.md` — the production checklist.
- `docs/0021-npub-prepaid-accounts.md` — account, P2PK-policy and log APIs.
- `docs/0022-app-relay-integration.md` — actual relay integration and next gates.
- `docs/0023-live-fips-application.md` — live peer application and release gates.
- `ROADMAP.md` — phases and exit criteria.
- `CHECKLIST.md` — live tracker.

## Layout

```
docs/          design notes, numbered
spec-drafts/   ready-to-PR text for OpenTollGate/tollgate
experiments/   one directory per experiment
harness/       lab topology, scripts, compose file
results/       one file per run; raw output first
```

The unmerged FIPS patches are deliberately **not** in this repository. They live
in the private `low-layer-tollgate-patches` repo, per `AGENTS.md`.

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
