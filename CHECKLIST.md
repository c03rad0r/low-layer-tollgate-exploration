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
- [x] `tollgate-fips` control-socket client (via `fipsctl`; not a raw socket)
- [x] Metering arithmetic + unit tests (63 tests across meter/session/journal/exposure/payment, `sidecar/tests/`)
- [x] Live meter smoke test on `host-b`
      (`results/S-2026-11-03-sidecar-meter.md`)
- [x] **Exp C** — cut and re-admit cost (`results/C-2026-11-03-cut-readmit.md`);
      n=4: bare reconnect 6.5–6.9 s, durable re-admit 2.7–2.9 s; no mint
- [x] **Exp H** — ACL-deny re-parenting (`results/H-2026-11-03-reparent.md`);
      109 ms re-parent, routing recovered, parent choice sticky
- [x] Durable eviction: deny → wait for ACL → disconnect (Exp C)
- [x] Two-node Exp C lab and three-node Exp H triangle (`harness/exp-c`, `harness/exp-h`)
- [ ] Buyer-exhausts demo (documented failure of pause)
- [x] `spec-drafts/04-pause-and-renewal.md` cites C's numbers

## Phase 2 — transports

- [~] `experiments/01-tcp` — cut/re-admit over TCP done, n=4
      (`results/01-tcp-2026-11-03.md`); bare reconnect 7.7–7.9 s,
      re-admit 2.8–3.6 s; payment/beacon pending
- [ ] `experiments/03-ethernet`
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
- [ ] Batch settlement
- [~] **Exp F** — offline verification with the mint stopped passes
      (`results/F-2026-11-03-offline-verify.md`); session continuity/journal wiring pending
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
