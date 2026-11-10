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
- [x] Metering arithmetic + unit tests (135 tests across meter/session/journal/exposure/payment/controller/settlement/vault/frame-gate/drain, `sidecar/tests/`)
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

- [x] (a) runtime admission mutation (`results/A2-2026-11-03-runtime-admission.md`)
- [x] (b) per-peer forwarding role — local patch + lab pass
      (`0001-per-peer-forwarding.patch` in the private patches repo,
      `PB-2026-11-03-per-peer-forwarding.md`)
- [x] `drop_policy_blocked_{packets,bytes}` + `fipsctl set-forwarding`
- [x] Multi-peer isolation: block A at B; C→D, A→B and the A–B link unaffected;
      drops filed under A only, n=3 (`results/MP-2026-11-03-multi-peer-isolation.md`)
- [x] (c) price in `link_cost` with hysteresis
      (`results/PRICE-2026-11-03-local-cost.md`; 351–513 ms soft switch, 3/3)
- [ ] **Exp D** — refused-initiator cost
- [x] Re-run with (b): pause with real payment, no disconnect
      (`results/PD-2026-11-03-pause-payment.md`)
- [x] Repeat capstone: 3/3 UDP and 3/3 TCP, link preserved every run
      (`harness/pause/repeat-pay-demo.sh`, `harness/pause-tcp/`)
- [x] Private patches repo marks every patch unmerged; patch (b) added
- [x] Prepare Signal write-up (private patches repo, `SIGNAL-DRAFT.md`; not sent)

## Phase 5 — spec PRs

- [x] Draft text for P1–P5 (`spec-drafts/01`–`04`, `06`)
- [x] `spec-drafts/README.md` maps titles, branches and evidence
- [x] P1 endpoint advertisement + port removal → TIP-08, PR #51
      (`tip/08-endpoint-advertisement`)
- [x] P2 scope → TIP-09, PR #52 (`tip/09-session-scope`)
- [x] P3 wire-byte metering → TIP-10, PR #53 (`tip/10-wire-byte-metering`)
- [x] P4 pause and renewal → TIP-11, PR #54 (`tip/11-pause-renewal`)
- [x] P5 frame gate → `ETH-01`, PR #55 (`eth/01-frame-gate`; medium spec,
      matching `WIFI-01`)
- [x] No PR opened without explicit operator approval
- [x] Each cites experiment IDs in the PR body and the TIP text
- [x] No README index change in any PR, to avoid cross-PR conflicts
- [x] Patches split into the private `low-layer-tollgate-patches` repo;
      `patches/` removed from this repo's history
- [x] Repo published; PRs #51–#55 link the public result files
- [x] Amperstrand and felixfelix-bot invited (`write`; GitHub does not allow
      `admin`/`maintain` on personal-account repos)

## Phase 6 — channels

- [ ] `cdk-spilman` behind the gate interface
- [ ] **Exp J** — cross-mint **time-to-pay** (buyer-side, not admission)
- [x] Treasury-path decision: swaps stay off the gate path
      (`docs/0018-treasury-plane.md`)

## Phase 7 — frame gate

- [x] nft `netdev` chain + MAC set — correctness on `veth`
      (`results/E-nft-2026-11-03.md`)
- [x] **Exp E2** — nft `netdev` lossless at 1k/10k/~99k pps; CPU inconclusive
      (`results/E2-2026-11-03-frame-gate-throughput.md`)
- [ ] **Exp E3** association-only bypass (needs a real AP)
- [x] **Exp E4** nft vs tc/BPF — per-MAC, identical effect; nft is the
      smallest (`results/E4-2026-11-03-per-mac-token-bucket.md`)
- [x] `FrameGate` module over nft: install/uninstall, block/unblock,
      authorise, bucket reset, `status()`/`buckets()`
      (`frame_gate.py`, 11 tests, `results/FRAMEGATE-2026-11-03-module.md`)
- [x] Module demo on real nftables 1.0.9: rate limit, block/unblock, allow-list
      (`harness/ethernet-lab/run-frame-gate-demo.sh`)
- [x] Wire `FrameGate.block`/`unblock` into `SellerController` after a
      durable eviction, with `unblock_frame()` on re-admission
      (5 controller tests)
- [ ] Wire the `ndsctl` half when the AP result exists
- [x] Draft `spec-drafts/06-frame-gate.md` (P5; opened as `ETH-01`, PR #55)
- [ ] **Exp E** — `ndsctl` deauth vs `0x2121` (needs a real AP)

## Phase 8 — balloon decision experiments

Plan and per-experiment checkboxes: `docs/0019-balloon-decision-experiments.md`.

- [~] D1 forwarding surface — BYPASS and SELECTOR complete; L2 is effective
      only at a verified cut vertex (BYPASS n=3); L0 allow-list needs an
      out-of-band rebind path (SELECTOR n=3). Deliberate E laundering and
      actual MAC spoof/roaming follow.
- [~] D2 key model — per-balloon compressed P2PK key validated offline;
      shared acceptors both credit, one loses on redemption (TWOKEY). More
      token samples and fleet sync remain.
- [~] D3 offline policy — correct crash ordering 0/20 double credit;
      expiry guard vs permissive mint; 30 s outage settles exactly
      (CRASH/EXPIRY/OUTAGE). Long outages, rotation and power cut remain.
- [~] D4 R2 vs R3 — R2 fits multi-minute contacts in the 255 B/30% loss
      model; use npub accounts rather than a short link deadline
      (LORA/INTERMITTENT). Actual RF/Wirehair scheduler remains.
- [x] D5 FIPS implementation — initial service gates at the full Rust ground
      daemon; current microfips is leaf-only, balloon-router cost is external.
- [x] E-INTERMITTENT — 60 s model evicted after deadline/grace; 7,200 s
      account survives; link ids change (n=1 per model)
- [x] E-BIND — FIPS source maps to npub; cross-peer token replay refused
- [x] Decisions D1–D5 and evidence links recorded in `docs/0019`

Remaining follow-ups: varied token/expiry series, long outage windows,
transit-laundering, MAC spoof/rebind, hardware LR2021/Wirehair runs, and
on-device flash/power-loss tests.

## Phase 9 — production readiness

Full plan: `docs/0020-balloon-production-readiness.md`; API notes:
`docs/0021-npub-prepaid-accounts.md`.

- [x] Narrow deployment contract: single app-relay or verified cut vertex,
      no per-balloon fleet key and no L0-selector authorization
- [x] Durable npub prepaid account (`account.py`): DECIMAL credit/use,
      dormant/contact-gap state, renewal, explicit eviction
- [x] Offline one-of-one P2PK admission (`nut11.py`): compressed seller key,
      no refund/locktime/multisig/unknown extension or sig-all
- [x] Bounded-record CRC append-only journal (`appendlog.py`): torn-tail
      handling, reopen, compaction, single-key latest pending
- [x] Cross-process account/payment demo (`harness/exp-account/account_demo.py`)
- [x] Host result (`results/ACCOUNT-2026-11-10-production-prototype.md`), 174 tests)
- [ ] Choose controller/router/service and write OFFER/PAY/ACK/status wire schemas
- [ ] Bind offline verification + reservation into one actual relay's accepted
      PAY handler; enforce balance on every forwarded/served request
- [ ] Use exact chargeable-frame metering (exclude policy drops).
- [ ] Resolve key lifecycle, durable key/offers, account read/write across OS
      reboot and initial clock expiry selection
- [ ] Real-mint reclaim vectors, keyset rotation and stale-keyset recovery
- [ ] End-to-end payer binding through an intermediate relay
- [ ] Embedded bounded storage: compaction cost/wear, corruption limits,
      multi-writer policy, and keyset exposure/cap controls
- [ ] Full process + flash power-cut at reserve / redeem / SETTLED
- [ ] Device HIL timing/RAM and actual LR2021/Wirehair contact-window timings
- [ ] Full multi-pass soak, seller restart, mint outage/reconnect and dead-letter
- [ ] Provisioning, signed release, signed rollback, kill switch, operator
      recovery runbook, monitored exposure/alarm expiry
- [ ] Pilot one mint, one relay, conservative capped exposure; publish evidence
      and review before scaling

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
