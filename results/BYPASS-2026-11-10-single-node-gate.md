# Result: BYPASS — is a single gated node enough?

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-BYPASS (docs/0019, decision D1)
- **Nodes:** `lt-byp-a`, `lt-byp-b`, `lt-byp-c`, `lt-byp-d`, one private Docker bridge
- **FIPS:** 0.6.0-dev (rev `2ba790b221`) plus the private per-peer forwarding patch
- **Status:** completed, n=3 fresh topologies

## Question

If B blocks A's transit, can A still reach D through C? Does blocking one node
block the path, or only one route through it?

## Setup

The intended tree is B root, A child of B, C child of B, D child of C. A also
has a direct link to C:

```text
B (root, passive)
| \
|  C --- D
| /
A (dials both B and C)
```

The per-peer forwarding policy blocks A at B while leaving the A–B link and
local delivery intact. Denying B on A and disconnecting A–B then forces a
re-parent to C. Each run started from a fresh compose project.

```sh
# From this repository, with real lab seeds substituted into configs/.
docker compose -f harness/exp-bypass/docker-compose.yaml up -d --remove-orphans
PYTHONPATH=./sidecar python3 harness/exp-bypass/bypass.py
```

## Raw measurements

| Run | Initial tree (A parent, C parent, D parent) | A→D after blocking A at B | Re-parent to C | A→D via C | A→D after blocking A at B and C |
|---|---|---:|---:|---:|---:|
| 1 | B, B, C | 100% loss | 260 ms | 0% loss | 100% loss |
| 2 | B, B, C | 100% loss | 283 ms | 0% loss | 100% loss |
| 3 | B, **A**, C | **0% loss** | 2268 ms | 33.3% loss (probe) | 100% loss |

For every run, blocking A at B left A→B and A→C working, C→D working, and the
A–B link connected. Blocking A at C subsequently produced 100% loss in all
three runs and in all three allow/block cycles per run.

Run 1:

```text
topology: {"a": {"parent": "b", "peers": 2}, "b": {"parent": null, "peers": 2}, "c": {"parent": "b", "peers": 3}, "d": {"parent": "c", "peers": 1}}
blocked at B: {"a_to_d": false, "a_to_b": true, "a_to_c": true, "c_to_d": true, "link_a_b": true}
after re-parent: {"topology": {"a": {"parent": "c", "peers": 1}, "b": {"parent": null, "peers": 1}, "c": {"parent": "b", "peers": 3}, "d": {"parent": "c", "peers": 1}}, "parent_c_ms": 260}
bypass a->d via C: {"ok": true, "loss_pct": 0.0}
blocked at B and C: {"ok": false, "loss_pct": 100.0}
cycle: {"cycle": 1, "allow_ok": true, "block_ok": false, "allow_loss": 0.0, "block_loss": 100.0}
cycle: {"cycle": 2, "allow_ok": true, "block_ok": false, "allow_loss": 0.0, "block_loss": 100.0}
cycle: {"cycle": 3, "allow_ok": true, "block_ok": false, "allow_loss": 0.0, "block_loss": 100.0}
```

Run 3 changed C's parent to A. That changes the route, not the policy:

```text
topology: {"a": {"parent": "b", "peers": 2}, "b": {"parent": null, "peers": 2}, "c": {"parent": "a", "peers": 3}, "d": {"parent": "c", "peers": 1}}
blocked at B: {"a_to_d": true, "a_to_b": true, "a_to_c": true, "c_to_d": true, "link_a_b": true}
...
bypass a->d via C: {"ok": true, "loss_pct": 33.3333}
blocked at B and C: {"ok": false, "loss_pct": 100.0}
```

The three full raw logs are retained in the lab; the summary above preserves
every gate-changing result rather than selecting only a passing run.

## Interpretation

1. **A per-node gate is sufficient only for traffic that traverses that node.**
   In runs 1–2 the route was A–B–C–D, and blocking A at B was effective. In run
   3 C was below A, so A→D used A–C–D and B's block did nothing. The difference
   is not intermittent packet loss or a policy failure; it is a different route.
2. **Forced re-parenting is an explicit bypass.** Once A re-parented to C,
   A→D worked in every run even with B still blocking A. A seller cannot point
   at one arbitrary mesh node and claim its transit rule reaches every path.
3. **Blocking both candidate routes closes it.** A→D failed completely once both
   B and C blocked A. The per-peer policy works; its scope is just the node where
   it is installed.
4. **Local delivery is not authorization to transit.** The A–B link and A→B/A→C
   still worked. That preserves the payment/debugging lane but proves nothing
   about whether transit is blocked.

## Decision for D1

For a balloon that is a verified cut vertex, an L2 per-peer transit block is the
right enforcement point. For a redundant mesh it is not enough: every candidate
transit parent must implement the same admission decision, or the paid service
must terminate at an app-level relay. Do not sell an end-to-end path from one
hop's policy state alone.

This does not make a bent-pipe allow-list an authorization mechanism. That
question is separately measured in `SELECTOR-2026-11-10-l0-selector-rebind.md`.

## Caveats and follow-ups

- Four nodes, one Docker bridge, UDP only. No radio, RF loss model, or third
  redundant path.
- Tree formation is timing-dependent. Parent choice was forced when A initially
  chose C, so route diversity is intentionally recorded rather than suppressed.
- No alternative-path billing reconciliation yet. Per-hop sellers must not charge
  for bytes they refused; that is already covered by the PD/MP policy-drop work.
- Follow-up: a true transit-laundering arm, with an admitted intermediary
  deliberately carrying a blocked peer's application traffic, in addition to the
  routing bypass shown here.

## Artefacts

- `harness/exp-bypass/` — compose, configs and orchestrator.
- Related: `results/PB-2026-11-03-per-peer-forwarding.md`,
  `results/MP-2026-11-03-multi-peer-isolation.md`,
  `results/H-2026-11-03-reparent.md`.
