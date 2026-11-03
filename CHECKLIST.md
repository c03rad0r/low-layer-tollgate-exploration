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

- [ ] Gate interface spec: `admit / deny / meter / pause / evict`
- [ ] `tollgate-fips` control-socket client
- [ ] Metering arithmetic + unit tests
- [ ] **Exp C** — cut and re-admit cost
- [ ] **Exp H** — ACL-deny re-parenting
- [ ] Buyer-exhausts demo (documented failure of pause)
- [ ] Draft `spec-drafts/04-pause-and-renewal.md` with C's numbers

## Phase 2 — transports

- [ ] `experiments/01-tcp`
- [ ] `experiments/03-ethernet`
- [ ] `experiments/04-ble`
- [ ] `experiments/02-tor`
- [ ] Shared acceptance test: same log, counters reconcile

## Phase 3 — mint + journal

- [ ] Local test mint in `harness/`
- [ ] Durable nullifier journal, fsync before credit
- [ ] P2PK-to-seller path
- [ ] Exposure cap + batch settlement
- [ ] **Exp F** — mint stopped mid-session
- [ ] **Exp G** — post-`final_expiry` behaviour
- [ ] Draft `spec-drafts/05-payer-binding.md`

## Phase 4 — FIPS patches

- [ ] (a) runtime admission mutation
- [ ] (b) per-peer forwarding role
- [ ] (c) price in `link_cost` with hysteresis
- [ ] **Exp D** — refused-initiator cost
- [ ] Re-run C with (b): pause replaces disconnect
- [ ] `patches/README.md` marks every patch unmerged
- [ ] Prepare Signal write-up (do not send)

## Phase 5 — spec PRs

- [x] Draft text for P1–P4 (`spec-drafts/01`–`04`)
- [ ] P1 endpoint advertisement + port removal — open PR
- [ ] P2 scope — open PR
- [ ] P3 wire-byte metering — open PR
- [ ] P4 pause and renewal — open PR after Exp C
- [ ] Each cites experiment IDs

## Phase 6 — channels

- [ ] `cdk-spilman` behind the gate interface
- [ ] **Exp J** — cross-mint time-to-admit
- [ ] Treasury-path write-up

## Phase 7 — frame gate

- [x] nft `netdev` chain + MAC set — correctness on `veth`
      (`results/E-nft-2026-11-03.md`)
- [~] **Exp E2** drop cost — correctness done; pps/CPU not measured
- [ ] **Exp E3** association-only bypass (needs a real AP)
- [ ] **Exp E4** nft vs tc/eBPF
- [ ] Wire to module alongside `ndsctl`
- [ ] Draft `spec-drafts/06-frame-gate.md`
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
