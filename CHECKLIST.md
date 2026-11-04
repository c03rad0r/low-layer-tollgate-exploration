# Checklist

Live tracker. `[~]` in progress, `[!]` blocked, `[x]` done. Move finished items
to the bottom with a date.

## Phase 0 — seams

- [x] Create repo, `AGENTS.md`, docs skeleton
- [x] **Exp A** — counter boundary: source inspection + fleet sample
      (`results/A-2026-11-03-counter-boundary.md`)
- [x] **Exp B** — ACL reload latency (host-b, 3 runs, 756–984 ms)
      (`results/B-2026-11-03-acl-latency.md`)
- [!] **Exp E** — captive-portal bypass: needs an Ethernet-transport lab pair
      (fleet has UDP+TCP only)
- [x] Write `docs/0007-current-enforcement.md`
- [x] Update roadmap if A/B/E change anything
- [x] **Exp E (nft half)** — `netdev` gate on `0x2121` + MAC set, on `veth`
      (`results/E-nft-2026-11-03.md`, `harness/ethernet-lab/`)
- [ ] Packet-capture confirmation of A on the lab Ethernet pair (Phase 2)

## Phase 1 — sidecar

- [x] Gate interface spec: `admit / deny / meter / pause / evict`
      (`docs/0008-gate-interface.md`)
- [x] `tollgate-fips` control-socket client (`fipsctl` plus raw `set_forwarding`)
- [x] Metering arithmetic + unit tests (119 tests across meter/session/journal/exposure/payment/controller/settlement/vault, `sidecar/tests/`)
- [x] Live meter smoke test on `host-b`
      (`results/S-2026-11-03-sidecar-meter.md`)
- [x] **Exp C** — cut and re-admit cost (`results/C-2026-11-03-cut-readmit.md`);
      n=4: bare reconnect 6.5–6.9 s, durable re-admit 2.7–2.9 s; no mint
- [x] **Exp H** — ACL-deny re-parenting (`results/H-2026-11-03-reparent.md`);
      109 ms re-parent, routing recovered, parent choice sticky
- [x] Durable eviction: deny → wait for ACL → disconnect (Exp C)
- [x] Pause via patched `set_forwarding` (`control.py`, 5 tests; validated
      against the PB seller container)
- [x] Seller controller: session state → pause/resume/evict + meter
      (`controller.py`, 8 tests; `results/CTRL-2026-11-03-seller-controller.md`)
- [x] Two-node Exp C lab and three-node Exp H triangle (`harness/exp-c`, `harness/exp-h`)
- [x] Buyer-exhausts demo with real offline ecash
      (`results/DEMO-2026-11-03-buyer-exhausts.md`): unpaid 14,274 B for 0 msat,
      durable evict, prepaid re-admit ≈1.75 s
- [x] `spec-drafts/04-pause-and-renewal.md` cites C's numbers

## Phase 2 — transports

- [x] `experiments/01-tcp` — cut/re-admit over TCP done, n=4
      (`results/01-tcp-2026-11-03.md`); bare reconnect 7.7–7.9 s,
      re-admit 2.8–3.6 s; payment/beacon pending
- [x] `experiments/03-ethernet` — discovery, metering, admission and pause
      (`results/01-ethernet-2026-11-03.md`, `results/PE-2026-11-03-pause-ethernet.md`)
- [ ] `experiments/04-ble`
- [ ] `experiments/02-tor`
- [ ] Shared acceptance test: same log, counters reconcile

## Phase 3 — mint + journal

- [x] Local test mint: Nutshell 0.21.0 + FakeWallet (`harness/mint/`)
- [x] Durable nullifier journal, fsync before credit
      (`sidecar/tollgate_fips/journal.py`, 13 journal tests; `docs/0009`)
- [~] P2PK-to-seller path: real lock verified offline in `harness/mint/`;
      not yet wired to `PaymentGate`
- [x] Exposure cap core (`sidecar/tollgate_fips/exposure.py`, 10 tests; `docs/0010`)
- [x] Payment gate ordering: verifier → exposure → journal
      (`sidecar/tollgate_fips/payment.py`, 8 tests; `docs/0011`)
- [x] Settlement: redeem → SETTLED → release, crash recovery from the token
      vault (`settlement.py`, `vault.py`, 17 tests, `results/SETTLE-2026-11-03-redeem.md`)
- [x] Batch settlement: 4 tokens in one swap, 1 sat vs ~4 (`results/BATCH-2026-11-03.md`)
- [x] Background timer that drains `vault.pending()`
      (`drain.py`, 5 tests, `results/DRAIN-2026-11-03-daemon.md`)
- [x] Dead-letter after `max_attempts` + `health()` (last pass/success/error,
      pending/dead counts) and `requeue`
      (`drain.py`, `vault.py`, 8+10 tests, `results/DEADLETTER-2026-11-03.md`)
- [~] **Exp F** — offline verification + durable replay refusal pass
      (`results/F-2026-11-03-offline-verify.md`); FIPS session continuity pending
- [x] **Exp G** — keyset `final_expiry` (`results/G-2026-11-03-final-expiry.md`):
      predicate rejects inside the window; Nutshell still accepts a spend after expiry
- [ ] Draft `spec-drafts/05-payer-binding.md`

## Phase 4 — FIPS patches

- [ ] (a) runtime admission mutation
- [x] (b) per-peer forwarding role — local patch + lab pass
      (`patches/0001-per-peer-forwarding.patch`, `PB-2026-11-03-per-peer-forwarding.md`)
- [x] `drop_policy_blocked_{packets,bytes}` + `fipsctl set-forwarding`
- [x] (c) price in `link_cost` with hysteresis
      (`results/PRICE-2026-11-03-local-cost.md`; 351–513 ms soft switch, 3/3)
- [ ] **Exp D** — refused-initiator cost
- [x] Re-run with (b): pause with real payment, no disconnect
      (`results/PD-2026-11-03-pause-payment.md`)
- [x] Repeat capstone: 3/3 UDP and 3/3 TCP, link preserved every run
      (`harness/pause/repeat-pay-demo.sh`, `harness/pause-tcp/`)
- [x] `patches/README.md` marks every patch unmerged; patch (b) added
- [ ] Prepare Signal write-up (do not send); PB is reproducible but one run

## Phase 5 — spec PRs

- [x] Draft text for P1–P4 (`spec-drafts/01`–`04`)
- [x] `spec-drafts/README.md` maps titles, branches and evidence
- [ ] P1 endpoint advertisement + port removal — open PR
- [ ] P2 scope — open PR
- [ ] P3 wire-byte metering — open PR
- [ ] P4 pause and renewal — open PR after Exp C
- [~] Each cites experiment IDs (drafts do; PRs not opened)

## Phase 6 — channels

- [ ] `cdk-spilman` behind the gate interface
- [ ] **Exp J** — cross-mint time-to-admit
- [ ] Treasury-path write-up

## Phase 7 — frame gate

- [x] nft `netdev` chain + MAC set — correctness on `veth`
      (`results/E-nft-2026-11-03.md`)
- [x] **Exp E2** — nft `netdev` lossless at 1k/10k/~99k pps; CPU inconclusive
      (`results/E2-2026-11-03-frame-gate-throughput.md`)
- [ ] **Exp E3** association-only bypass (needs a real AP)
- [x] **Exp E4** nft vs tc/BPF — per-MAC, identical effect; nft is the
      smallest (`results/E4-2026-11-03-per-mac-token-bucket.md`)
- [ ] Wire the nft rule/set to session state in the module (with `ndsctl`
      when the AP result exists)
- [x] Draft `spec-drafts/06-frame-gate.md` (P5; not opened)
- [ ] **Exp E** — `ndsctl` deauth vs `0x2121` (needs a real AP)

## Cross-cutting

- [ ] Every result file has version, rev, commands, raw output
- [ ] `df -h` on any fleet node before writing
- [ ] No mainnet funds
- [ ] `CHECKLIST.md` updated in the same commit as the work

## Open questions

- [ ] Q1 baseline FIPS version: fleet 0.5.3 vs local 0.6.0-dev build
- [ ] Q2 local mint image: ours or reuse
- [ ] Q3 BLE hardware on any fleet node
- [ ] Q4 default exposure cap for link sessions
