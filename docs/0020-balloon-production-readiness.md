# 0020 — Balloon production readiness plan

Status: host prototypes complete; production acceptance open
Owner: c03rad0r
Related: `docs/0019-balloon-decision-experiments.md`, `docs/0009`–`0016`,
`results/BYPASS-2026-11-10-single-node-gate.md`,
`results/TWOKEY-2026-11-10-offline-shared-key.md`,
`results/INTERMITTENT-2026-11-10-contact-gap.md`.

## Initial product contract

Sell **prepaid access to one narrowly-scoped ground-side application relay**,
or prepaid transit along **one verified routing-parent/cut-vertex path**. Never
claim arbitrary end-to-end or all-mesh connectivity from one hop's policy.

| Decision | Initial production contract |
|---|---|
| Client | FIPS peer authenticated by npub; no IP/MAC-based account or credit |
| Offer | Scope, transport endpoint, price, charge directions, measurement step, allowed mints/keysets, settlement and dormant expiry policies |
| Payment | One-of-one NUT-11 P2PK to this seller's **33-byte compressed key**, with DLEQ verification |
| Account | Durable prepaid account keyed by npub; a new `link_id` is a transport incident, not a new account |
| State | `unpaid → paid → grace/dormant → evicted`; link loss alone never proves non-payment |
| Enforcement | For app relay, reject requests in its handler. For arbitrary FIPS transit, gate at every relevant forwarding parent; do not make that claim for a leaf router |
| Time | Account deadlines outlast contact gaps; separate settlement wall-clock expiry from a monotonic service deadline |
| Offline cash | Small bounded exposure, deferred settlement, unknown keysets and near-expiry notes refused |
| Uncertainty | Stop new paid acceptance; do not turn uncertain money state into free service |
| Scope exclusions | No shared fleet keys, no transparent bent-pipe authorization, no Granola/cross-mint swaps in admission |

### Readiness gates

Shipping requires all these to be true on the actual shipped configuration:

1. No credit without verified proof and durable reservation.
2. No duplicate credit after replay, reconnect, retry, process crash or power cut.
3. No paid forwarding when unpaid, exhausted or uncertain.
4. Money accepted offline resolves to settled, rejected or visibly recoverable.
5. Credit survives contact gaps, link changes and seller restarts by npub.
6. Unknown keysets, expiry-late notes, cap exhaustion and journal failures close safely.
7. Real LR2021 payment and metering fit contact windows with tolerable retry stories.
8. Flight SKU signs/debug keys are absent; key loss/compromise has a bounded recovery path.
9. Set/measurement overshoot is stated and acceptable; policy drops are unbilled.
10. Signed release, explicit rollout/rollback and operator recovery tooling exist.

## Phase 0 — Enforce the contract boundary

- [x] Sell no universal/all-mesh promise from a single path; settle the initial app-relay/cut-vertex distinction.
- [x] Define unpaid, paid, grace and dormant behavior.
- [x] Account must be bound to npub, not IP, MAC or `link_id`.
- [ ] Select exact application-relay service and its routing-parent topology.
- [ ] Select offer numbers: rate, charge direction, metering step, expiry, grace/dormant durations, offline caps.
- [ ] Freeze a wire schema for OFFER, PAY, ACK, REJECT and account-status messages.
- [ ] Sign or cryptographically bind the FIPS identity and the distinct payment lock key in the offer.

## Phase 1 — Router and forwarding enforcement

- [x] Establish that current public microfips is a single-upstream **leaf**, not a tariff-enabled transit router (`results/FEATURES-2026-11-10-fips-implementation-matrix.md`).
- [x] Keep deployment target grounded: full Rust relay daemon for the initial app service.
- [ ] Resolve the `balloon-fresh` ADR-016 "C++ microfips" text versus the current Rust/no_std implementation with the balloon owner.
- [ ] Re-key `tollgate_core_session`/`tollgate_core_firewall` away from WiFi IP/MAC/NAPT to authenticated FIPS identity.
- [ ] Integrate the account policy into *one real* relay controller; API scaffolding alone is not a working relay.
- [ ] Decide: full FIPS-capable balloon companion router vs microfips-router extension. Require a router profile plus per-peer transit policy and counters if Option B.
- [ ] Measure all candidate routes and verify the cut vertex, rather than assuming it.
- [ ] Test renewal, exhaustion, blocked local delivery and unchanged payment lane at that chosen enforcement point.

## Phase 2 — Durable money and accounts (host prototype complete)

- [x] Add durable `PrepaidAccount`/`PrepaidAccountStore` keyed by npub (`sidecar/tollgate_fips/account.py`).
- [x] Renewal retains usage; no reset on top-up.
- [x] DORMANT preserves balance and disables forwarding with no active link.
- [x] `link_up(npub, new_id)` refuses mismatched account identities.
- [x] Expiry goes through grace before eviction; contact loss is not itself expiry.
- [x] Store Decimal balances and resume state durably with SQLite WAL + `synchronous=FULL`.
- [x] Demonstrate cross-process dormant/recovery accounting in `harness/exp-account/account_demo.py`.
- [x] Add tests for gap, grace, avoidable overshoot, mismatched identity and exact-balance restart: `sidecar/tests/test_account.py`.
- [ ] Restrict debit to whole declared chargeable FMP-frame count; don't accidentally bill payload estimates or policy-dropped frames.
- [ ] Bind a verified P2PK payment into the actual account persistence path in one controller.
- [ ] Handle session deadline validity across whole-OS reboot; host store is not proof of hardware clock durability.
- [ ] Persist accounts on embedded storage without falling back to per-frame whole-database rewrites.
- [ ] Demonstrate account recovery under a broken/corrupt store and after failed compaction.

## Phase 3 — Offline P2PK policy

- [x] Require the 33-byte compressed lock key; x-only npubs are rejected (`nut11.py`).
- [x] Exact one-of-one P2PK matching; external key or mint mismatch fails before forwarding.
- [x] Reject refund, locktime, multisig (`n_sigs`, `pubkeys`), `SIG_ALL`, grouped-witness extensions and unknown fields/tags for offline acceptance.
- [x] Apply keyset `final_expiry` with settlement window (settlement deadline, not account clock).
- [x] Unit-test positive P2PK and malicious NUT-11 variants (`test_nut11.py`).
- [ ] Add real-mint vectors for malformed and reclaim-bearing conditions rather than only constructed policy dictionaries.
- [ ] Choose whether to provision keysets offline or from a trusted ground source; do not trust arbitrary client-provided keys.
- [ ] Test keyset rotation and stale-keyset recovery while offline.
- [ ] Decide how to delegate the DLEQ/P2PK parser and verifier into constrained firmware without weakening policy.
- [ ] Exercise payer binding through an intermediate hop, including the preamble/msg1-ephemeral design before any normative TIP.

## Phase 4 — Embedded journal and settlement

- [x] Add bounded-record CRC-framed append-only journal `sidecar/tollgate_fips/appendlog.py`.
- [x] Record RESERVED/SETTLED/SPENT using proof-keyed records; append then fsync before returning.
- [x] Drop only incomplete last record on recovery; never invent credit from a torn tail.
- [x] Corrupt headers, CRCs and unknown fields fail closed.
- [x] Compaction preserves each proof's last state; post-settle reservations are not pending.
- [x] Tests cover reopen, replay, truncation at every offset, corruption and recovery (`test_appendlog.py`).
- [ ] Introduce independent account/log namespace/version interoperability across controller and settlement code.
- [ ] Cap outstanding entries and benchmark flash-life wear, compaction wall time and RAM use on real boards.
- [ ] Review embedded write atomicity, lock ownership and readers/writers during settlement.
- [ ] Guarantee no silently lost redeem→SETTLED window under reboot: consult mint before marking settled or retrying crediting.
- [ ] Implement deferred batch redemption, backoff, `REJECTED`, `DEAD-LETTER` and explicit requeue.
- [ ] Expose unsettled exposure, nearest expiry, redemption failures, dead-letter amounts and health to an operator.
- [ ] Real power-cut testing on flash erase/write, especially between vault/reserve and credit.

## Phase 5 — Identity, key safety and abuse controls

- [x] FIPS-source → npub mapping is usable; claimed payer never overrides link identity (`results/BIND-2026-11-10-fips-payment-binding.md`).
- [x] Fleet/shared P2PK keys are rejected for offline independent acceptors (`TWOKEY`).
- [ ] Provision a unique production redemption key before first deployment.
- [ ] Make redemption-only payment keys preferable to sharing FIPS identity keys.
- [ ] Secure element vs software-key decision, plus key rotation, revocation and recovery process.
- [ ] Bound links/accounts/verification attempts/pending reservations to reduce flash/CPU denial-of-service.
- [ ] Implement low-rate first-contact/payment lane or out-of-band checkout before any default-drop L0 gate.
- [ ] Implement rebind/channel update if L0 allow-lists remain optional fast paths.
- [ ] Keep source-address/MAC selectors explicitly advisory, never payer verification.

## Phase 6 — Release acceptance (hardware required)

- [ ] Fresh flash with debug seeds absent; verify payment key provisioning.
- [ ] Single valid note enables only the intended account/service.
- [ ] Mint-down acceptance inside cap works; settlement succeeds on the next uplink.
- [ ] Process crash before and after reserve/redeem/settle is safe.
- [ ] **Actual power cut** before and after reserve/redeem/settle is safe on deployed flash/boards.
- [ ] Same-peer replay, different-peer replay, ACK-loss retry: no new credit.
- [ ] Exhaustion pauses; later top-up resumes without resetting usage.
- [ ] Contact gap, rebind, link-id changes do not evict an account solely due to link absence.
- [ ] Unknown keyset, future invalid conditions, expiry-late notes, cap exhaustion and journal corruption fail closed.
- [ ] Spend then dead-letter produces an alarm, not false settlement.
- [ ] Asymmetric metering agrees with seller counters within the declared tolerance/step.
- [ ] Actual LR2021/Wirehair payment fits **less than half** the expected pass budget at p95, with an ACK-loss test.
- [ ] Fault-injected RTC/GPS loss cannot extend settlement validity incorrectly.
- [ ] Soak over several representative passes with a seller restart and a recovering mint.
- [ ] Evidence pack: exact builds/configs/scripts/raw result files and version hashes published without secrets.

## Phase 7 — Operations and release

- [ ] Offer manual and client note-acquisition flow for an offline ground station.
- [ ] Recovery runbook: inspect pending exposure, resolve mint-spent/dead-letter, diagnose corrupt journal.
- [ ] Sweep/redemption and mint-expiry operational instructions.
- [ ] Loss/capture playbook: revoke seller key, block fresh notes, audit unsettled credit and sweep what can be swept.
- [ ] Signed and pinned release images, schema version, rollback, disable switch.
- [ ] Pilot one mint, one relay, tiny per-payer and total caps; no production-scale denominations until recovery is demonstrated.
- [ ] Set production caps from measured device limits, contact windows and loss tolerance, not lab defaults.
- [ ] Re-run all acceptance gates when FIPS, mint, protocol schema or radio drivers change.

## Host evidence in this repository

- Tests: `PYTHONPATH=./sidecar python3 -m pytest sidecar/tests -q`.
- Repro demo: `python3 harness/exp-account/account_demo.py` (two separate processes).
- Functional result: `results/ACCOUNT-2026-11-10-production-prototype.md`.
- Other prior gates: E-BYPASS, E-SELECTOR, E-TWOKEY, E-CRASH, E-EXPIRY,
  E-OUTAGE, E-LORA, E-INTERMITTENT and E-BIND in `results/`.

**Current verdict:** not release-ready. Account/P2PK/journal prototypes and host
unit tests are real deliverables. There is still no deployed relay controller
with this contract, no flight-firmware storage proof, no physical-route/RF proof,
and no production signing/recovery workflow. The remaining hardware and
integration checkboxes are the work, not optional polish.

## Deliberately out of scope for the first production release

- A shared fleet key or fleet-wide offline synchronization.
- Arbitrary all-mesh/e2e forwarding from a leaf.
- Local mint (R3), which is a separate trust and resource project.
- Payment channels/cdk-spilman and Granola/treasury swaps in the admission path.
- BLE/Tor releases and a default-deny bent-pipe allow-list.
- Production mainnet money before the hardware gates and loss economics are known.
