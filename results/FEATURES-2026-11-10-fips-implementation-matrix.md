# Result: FEATURES — which FIPS stack can host a balloon tollgate?

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-FEATURES (docs/0019, decision D5)
- **Method:** implementation/source evidence; no hardware run
- **Status:** feature matrix completed; resource-cost measurement deferred

## Question

Can microfips provide the forwarding policy, per-peer counters and control API
needed for a paid relay, or must that gate run in the full Rust FIPS daemon?

## Evidence

### microfips

Public `Amperstrand/microfips` at the review date is Rust/no_std, not a C++
router. The protocol implementation documents its role explicitly:

`crates/microfips-protocol/src/node.rs:257–258`:

> "FMP node profile we advertise in negotiation. microfips is a leaf (single
> upstream peer, no tree/bloom/transit); tests and non-leaf deployments override
> via `Node::set_node_profile`."

The README ("Minimal FIPS leaf node on STM32F469I-DISCO and ESP32-D0WD") also
shows a leaf connecting to a full FIPS daemon. Its ESP32 control layer exposes
status and peer commands, and its protocol/metric code records MMP link traffic,
but this is not evidence of a router's per-peer transit authorization hook.

### Full FIPS daemon

The local full daemon used in experiments is 0.6.0-dev (`2ba790b221`), with UDP,
TCP and Ethernet data-plane routing and per-link statistics. The private patch
adds the per-peer forwarding role, runtime admission and price controls. Source
inspection of a fresh upstream checkout at `0294264` found no corresponding
`set_forwarding`, `forwarding_blocked`, `acl_overrides`, `set_admission` or
`set_price` definitions; no issue or PR was opened against `jmcorgan/fips`.

## Feature matrix

| Capability needed at the seller | microfips today | Full daemon in this lab |
|---|---|---|
| Can be a real mesh transit parent (not just leaf) | **No documented transit role; default is single-upstream leaf** | Yes: tree/routing and per-link dataplane |
| Per-peer `unpaid`/`grace` transit block without dropping link | No hook found; transit is outside the stated role | Private patch demonstrated; not upstream |
| Per-peer byte counters | MMP/link metrics are not the same as a router's tariff meter | Per-link counters plus private per-peer drop counters |
| Runtime admission/control socket | ESP32 status/peer control; no full router policy API shown | Control socket plus private `set_admission` |
| Rekey / roaming across contact gaps | Rekey verified in microfips docs; DTN account handling untested | New link id after reconnect; identity remains npub (E-INTERMITTENT) |
| Multi-hop BGP-like routing/loop avoidance | Not applicable to stated leaf role | Full tree dataplane, route-dependent (E-BYPASS) |
| Embedded fit | `no_std`, microcontroller-oriented | Host daemon; memory/CPU irrelevant to this comparison but unproven on balloon MCU |

## Interpretation

1. **The gate cannot be placed in today's microfips just because it is a leaf
   of FIPS.** A leaf does not offer the routing decision a balloon needs to sell
   transit; its verified counter/control features are different features.
2. **The economically meaningful decision has to run at a full routing node.**
   A ground Rust daemon can gate an app relay and can gate transit through that
   particular node (with the private forwarding hook). E-BYPASS shows this is
   not sufficient if it is not on every route.
3. **A balloon-as-tollgate is a different firmware requirement than a balloon-as-
   leaf.** It needs a router-capable node profile, per-peer policy and counters,
   or it must deliberately terminate a paid app service that does not forward
   arbitrary mesh transit.

## Decision for D5

Use the full Rust ground daemon for the initial paid relay/tollgate. Treat the
balloon as a leaf unless a separate routing-capable balloon firmware is built
and measured.

If the balloon itself must be the paid router, D5 is **not decided**: first add
and measure a router role, a per-peer policy hook and per-peer counters in its
stack, plus its cost on real hardware. Do not equate microfips's successful
handshake/service tests with permission to forward at L2.

The `balloon-fresh` ADR-016 text says "Keep C++ microfips". That needs
reconciliation with the current public Rust/no_std project before making a
specific firmware commitment; it is a document/implementation mismatch, not a
feature omitted from the design.

## Caveats and follow-ups

- Source and documentation review only; no MCU timing, RAM/flash, packet-per-
  second cost, or power measurement. Those are the external E-MICROFIPS work.
- This is not an answer on every future version of upstream fips or microfips.
  Re-run when a router profile exists in either repository.
- No FIPS PR/issue was opened as part of this analysis, and no unmerged local
  FIPS change has been published.

## Artefacts / references

- `https://github.com/Amperstrand/microfips` (reviewed source and README).
- `results/BYPASS-2026-11-10-single-node-gate.md` (why a routing policy matters).
- `results/PB-2026-11-03-per-peer-forwarding.md`,
  `results/MP-2026-11-03-multi-peer-isolation.md` (private-hook behavior).
