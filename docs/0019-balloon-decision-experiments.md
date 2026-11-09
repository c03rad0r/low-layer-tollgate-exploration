# 0019 — Balloon decision experiments

Status: planned, not started
Date: 2026-11-09
Owner: c03rad0r

This note turns the balloon architecture questions into experiments that can be
run in this repository, without balloon hardware and without touching upstream
FIPS. It exists so the five decisions are made from measurements rather than
from the shape of the current code.

Related material:

- `docs/0001-three-seams.md` — L0/L1/L2 and why identity appears at L1.
- `docs/0009`–`0018` — journal, exposure, payment gate, settlement, drain,
  frame gate, treasury boundary.
- `results/F-2026-11-03-offline-verify.md` — P2PK + DLEQ with the mint stopped.
- `results/G-2026-11-03-final-expiry.md` — `final_expiry` is not enforced by
  Nutshell 0.21.0.
- `results/SETTLE`, `BATCH`, `DRAIN`, `DEADLETTER`, `PD`, `MP`, `PE`.
- `balloon-fresh`: `docs/adr/100-tollgate-over-fips-mesh-udp.md`,
  `docs/adr/110-tollgate-over-lr2021.md`,
  `docs/adr/014-bent-pipe-fpga-bridging.md`,
  `docs/balloon/BALLOON-SCOPE-DECISIONS.md` (R1/R2/R3).

## Decisions this plan is meant to settle

| ID | Decision | Current leaning | Experiments |
|---|---|---|---|
| D1 | Forwarding surface | FIPS L2 per-peer transit plus an app-level relay; never claim per-packet gating on a transparent pipe | E-BYPASS, E-SELECTOR |
| D2 | Key model | Per-balloon P2PK key for offline; a fleet key only with a shared journal | E-TWOKEY |
| D3 | Offline policy | Cap unsettled value; settle before `final_expiry`; allow-list mints and keysets | E-CRASH, E-EXPIRY, E-OUTAGE |
| D4 | R2 vs R3 | Pre-loaded npub-locked notes on the balloon; a local mint, if any, on the ground side | E-LORA (plus external E-MINT) |
| D5 | FIPS implementation | Whichever stack can host the per-peer hook at acceptable cost; the Rust lab is the reference | E-FEATURES (plus external E-MICROFIPS) |

The leanings are not conclusions. Each experiment below states what result would
change the leaning.

## Conventions

- Test ecash only. No mainnet funds, no production mints.
- Local labs and unmerged local patches only. No PRs or issues against
  `jmcorgan/fips`; the per-peer forwarding patch is private and is referenced by
  behaviour, not republished.
- Every run writes `results/<ID>-<date>.md` before it is summarised anywhere
  else, raw output first, interpretation second.
- n=3 for timing/topology runs; n=10 for double-spend arms; n=20 per injection
  point for crash tests.
- Record FIPS version and rev, commit, commands, and exact topology in the
  result file.

## Status

- [ ] E-BYPASS — is a single gated node enough?
- [ ] E-SELECTOR — can an L0 allow-list follow a FIPS session?
- [ ] E-TWOKEY — per-balloon key vs fleet key
- [ ] E-CRASH — does the journal survive a crash without double-credit?
- [ ] E-EXPIRY — how long is the safe settlement window?
- [ ] E-OUTAGE — how much value is at risk in an outage?
- [ ] E-LORA — does a payment fit in a contact window?
- [ ] E-INTERMITTENT — does credit survive a contact gap?
- [ ] E-BIND — is payment bound to the FIPS session?
- [ ] E-FEATURES — feature matrix for microfips vs the Rust stack
- [ ] Decisions D1–D5 recorded in the table above

## E-BYPASS — is a single gated node enough?

**Decision:** D1.

**Question:** if node B blocks A's transit, can A reach D through another
admitted node C? Does blocking one node gate a path, or only one route?

**Setup:** four-node diamond on the private lab bridge:

```
    A ---- B
    | \  / |
    |  \/  |
    |  /\  |
    | /  \ |
    C ---- D
```

Links: A–B, A–C, B–D, C–D, B–C. Strict ACLs. FIPS 0.6.0-dev plus the private
per-peer forwarding patch. Use `harness/exp-multipeer` and `harness/exp-h` as
the starting point; add a second path.

**Procedure:**

- [ ] Form the diamond and assert the parent tree before measuring.
- [ ] Baseline A→D: loss, throughput, path, `link_id`s.
- [ ] Block A at B (`set_forwarding allow=false`); measure A→D and the tree.
- [ ] Record whether FIPS re-parents around B and how long that takes.
- [ ] Block A at B and C; measure A→D again.
- [ ] Transit-laundering arm: admit E, have E forward A's traffic, and measure
      whether A→D works through E.
- [ ] Write `results/BYPASS-<date>.md` and record the D1 decision.

**Measurements:** A→D loss and throughput; parent/path changes; time to bypass;
`policy_blocked_by_peer` attribution; whether blocked bytes are billed.

**Decision rule:** if A→D survives with only B blocked, a single gated node is
not a transit gate. The balloon must be verified as a cut vertex, or gating must
be at every hop or at the endpoints. If A→D fails only when every path is
blocked, per-node gating is sufficient for that topology.

**Effort:** 2–3 days. **Needs:** no balloon hardware.

## E-SELECTOR — can an L0 allow-list follow a FIPS session?

**Decision:** D1, specifically whether a bent-pipe allow-list is viable.

**Question:** can an L0 selector (Ethernet MAC, UDP 5-tuple, or a radio link id)
stay bound to one FIPS peer across rebind, reconnect and rekey, without a large
loss window?

**Setup:** two-node UDP lab and the Ethernet `veth` lab. An nft allow-list keyed
on the selector, driven by the gate's admission state.

**Procedure:**

- [ ] Admit A and pass traffic through the L0 allow-list.
- [ ] Force a UDP source-port rebind; measure whether the link survives and
      whether the selector changes.
- [ ] Force a reconnect; measure the allow-list update gap and packet loss.
- [ ] Repeat on Ethernet with a MAC change.
- [ ] Spoof A's selector from another host; record that it passes, confirming
      the allow-list is not authorisation.
- [ ] Write `results/SELECTOR-<date>.md`.

**Measurements:** selector stability, update latency, packets lost during the
update, whether a spoofed selector passes.

**Decision rule:** if the selector drifts on rebind and the update costs more
than the acceptable loss window, the bent-pipe allow-list is fragile; terminate
FIPS at the balloon and gate at L2. A stable selector makes an allow-list viable
for admitted peers, never for payment.

**Effort:** 1–2 days. **Needs:** no balloon hardware.

## E-TWOKEY — per-balloon key vs fleet key

**Decision:** D2.

**Question:** with two acceptors and the mint offline, does a shared P2PK key
permit double-credit? Does a per-acceptor key prevent it?

**Setup:** one Nutshell mint, one payer wallet, two seller verifiers S1/S2 with
separate journals. Three arms:

1. Same P2PK key on both acceptors.
2. Different keys.
3. Same key plus an opportunistic journal sync before S2 accepts.

**Procedure:**

- [ ] Payer swaps into a note locked to the shared key (arm 1) or S1's key
      (arm 2). Stop the mint.
- [ ] Present the note to S1; confirm acceptance and journal RESERVED.
- [ ] Present the same note to S2; record accept/reject and why.
- [ ] Restart the mint and redeem from both; record which succeeds.
- [ ] Arm 3: sync S1's journal to S2, then present; record the sync window and
      whether S2 rejects.
- [ ] Repeat each arm n=10.
- [ ] Write `results/TWOKEY-<date>.md`.

**Measurements:** acceptance rate at S2, redemption success, value lost, time to
detect, sync latency.

**Decision rule:** any same-key double-credit means a fleet key is unsafe
offline; per-balloon keys are required. If sync reliably closes the window
within the contact schedule, a fleet key becomes a policy choice rather than a
correctness bug.

**Effort:** 1–2 days. **Needs:** Nutshell lab only.

## E-CRASH — does the journal survive a crash?

**Decision:** D3, and whether R2 can be safe on flash at all.

**Question:** can the seller be killed between verification, credit and
settlement without double-crediting or losing a note?

**Setup:** the sidecar journal and `PaymentGate` in a container. Fault injection
at six points: after verify, after exposure reserve, after journal RESERVED,
after forwarding, after redeem, after SETTLED. Then a prototype append-only log
(record + CRC + commit marker) with truncated tails.

**Procedure:**

- [ ] Add a fault-injection hook to the payment path (test build only).
- [ ] `kill -9` at each point; restart; replay the token; record the outcome.
- [ ] Confirm replay is refused and the note is either credited or available,
      never both.
- [ ] Truncate the append-only log at random offsets; boot; record recovery.
- [ ] Repeat n=20 per injection point.
- [ ] Write `results/CRASH-<date>.md`.

**Measurements:** double-credit count, lost-credit count, recovery time, journal
truncation tolerance.

**Decision rule:** any double-credit means the journal design is wrong; reserve
before forwarding is necessary but not sufficient. This is the experiment most
likely to invalidate the "easy offline" story on ESP32, where SPIFFS/LittleFS is
not SQLite.

**Effort:** 2–3 days. **Needs:** no balloon hardware, but the append-only log is
the design input for the embedded journal.

## E-EXPIRY — how long is the safe settlement window?

**Decision:** D3.

**Question:** how close to `final_expiry` can a seller accept a note, and what
happens if the keyset rotates while it is offline?

**Setup:** `harness/mint/expiry.py` with a short `final_expiry`. Seller offline;
notes accepted; settlement attempted at `expiry − window`, at expiry, and after
expiry. Add a keyset rotation while offline.

**Procedure:**

- [ ] Set a short `final_expiry` and record it.
- [ ] Accept notes offline.
- [ ] Settle before, at, and after expiry; record admission and redemption.
- [ ] Rotate the keyset while the seller is offline; present old- and
      new-keyset notes.
- [ ] Vary the window across 1 minute, 1 hour and 1 day.
- [ ] Write `results/EXPIRY-<date>.md`.

**Measurements:** acceptance/rejection at each point, value lost, stale-keyset
behaviour, safe offline duration.

**Decision rule:** if notes fail inside the intended window, lengthen the window
or shrink the offline cap. Frequent rotation implies a keyset refresh policy and
rejection of unknown keysets.

**Effort:** 2 days. **Needs:** Nutshell lab only.

## E-OUTAGE — how much value is at risk?

**Decision:** D3.

**Question:** for a balloon-like outage, how much unsettled value accumulates,
and what cap keeps the loss acceptable?

**Setup:** seller offline for scaled durations (1, 6, 24, 72 hours); accepts
notes up to several caps; reconnects and batch-settles. Adversarial arm: the
mint reports `SPENT` after the seller accepted offline.

**Procedure:**

- [ ] Define caps (per payer and total) and record them.
- [ ] Accept notes offline for each duration.
- [ ] Restart the mint; batch-settle; record fees and time.
- [ ] Simulate a mint-side spend and record dead-letter/loss handling.
- [ ] Model loss against cap and outage length.
- [ ] Write `results/OUTAGE-<date>.md`.

**Measurements:** unsettled value, failure rate, fees, settlement time,
dead-letter count.

**Decision rule:** the cap is the maximum loss the operator accepts for the
longest plausible outage. If the failure rate after a long outage is high,
require online settlement before large credit.

**Effort:** 2 days. **Needs:** Nutshell lab only.

## E-LORA — does a payment fit in a contact window?

**Decision:** D4.

**Question:** how long does a Cashu payment take over 255-byte frames at LoRa
rates with loss, and what token sizes are viable?

**Setup:** a UDP proxy that fragments PAY/ACK into 255-byte frames, drops 30%,
and retries. Test 1/2/4/8-proof tokens at 1, 5 and 22 kbps. Add an ACK-loss arm
where the payer retries and the seller must dedupe.

**Procedure:**

- [ ] Measure token sizes for each proof count.
- [ ] Fragment and deliver at each rate; record fragments, retries and
      time-to-pay.
- [ ] Drop ACKs and force a PAY retry; confirm no double-credit.
- [ ] Write `results/LORA-<date>.md`.

**Measurements:** bytes, fragments, time-to-pay, retry count, failure rate,
duplicate detection.

**Decision rule:** if time-to-pay is a large fraction of the contact window, R2
must sell larger chunks or move to R3. If retries double-credit, the journal key
must be the proof, not the message.

**Effort:** 1–2 days. **Needs:** no radio; emulation only.

## E-INTERMITTENT — does credit survive a contact gap?

**Decision:** D3/D4, and whether the four-state model needs a dormant state.

**Question:** does a session keep its credit across a balloon-like contact gap
(up for minutes, down for an hour), or does it expire or evict?

**Setup:** a link that is up for 5 minutes and blackholed for 90 minutes
(scaled), with the seller controller and a prepaid session.

**Procedure:**

- [ ] Establish a paid session and pass traffic.
- [ ] Blackhole the link for the gap; restore it.
- [ ] Measure credit before/after, re-admission time, and state transitions.
- [ ] Repeat with `valid_until` shorter and longer than the gap.
- [ ] Write `results/INTERMITTENT-<date>.md`.

**Measurements:** credit preserved, link id, re-admission time, false evictions.

**Decision rule:** if credit or state is lost on a normal pass gap, decouple
credit from the link: a long-lived prepaid account keyed by npub, with the link
as an intermittent transport. If `evicted` fires during a gap, the grace
duration is wrong.

**Effort:** 2 days. **Needs:** no balloon hardware.

## E-BIND — is payment bound to the FIPS session?

**Decision:** D2/D3, and whether payer binding is needed before offline credit.

**Question:** can a PAY message or token presented from another npub be
credited, and can the seller tell who paid?

**Setup:** two FIPS peers A and B, a seller, and a PAY message generated by A.
Replay the PAY from B; also present A's token from B first.

**Procedure:**

- [ ] Send PAY over A's session; record the credit and the credited npub.
- [ ] Replay the same PAY from B; record whether it is accepted and credited.
- [ ] Present the token from B first; record who gets credit.
- [ ] Write `results/BIND-<date>.md`.

**Measurements:** credited npub, replay acceptance, duplicate detection.

**Decision rule:** if a replay or a different presenter gets credit, add a
signed binding (the design in `docs/0003`) or at minimum credit the npub that
sent the PAY and log the proof-to-npub mapping.

**Effort:** 1 day. **Needs:** no balloon hardware.

## E-FEATURES — feature matrix for the FIPS implementation

**Decision:** D5.

**Question:** which stack can host the gate's required hooks, and at what cost?

**Setup:** a written matrix, not a lab run, comparing microfips (C++) and the
Rust stack on the features the gate needs.

**Procedure:**

- [ ] Per-peer forwarding policy hook.
- [ ] Per-peer byte counters and policy-drop attribution.
- [ ] Runtime admission / control API.
- [ ] Rekey and rebind behaviour.
- [ ] Multi-hop routing visibility.
- [ ] Resource cost per peer and per packet.
- [ ] Record the matrix in `docs/0019` or a follow-up note.

**Decision rule:** if microfips cannot expose the hook or counters without a
rewrite, the gate belongs at the ground station or in the Rust daemon, and the
balloon remains an L2 relay. If it can, define one policy API for both.

**Effort:** 1–2 days for the matrix; hardware measurement is external
(E-MICROFIPS in `balloon-fresh`).

## Dependencies outside this repository

- **E-MINT** — can a mint run on the balloon? Resource-limit a mint container to
  ESP32-C3-like constraints, and separately run it on a Raspberry Pi ground
  station. Expect the balloon to be infeasible and the ground side feasible.
  Track in `balloon-fresh`.
- **E-MICROFIPS** — build the hook and measure CPU/RAM/flash on C3/LR2021.
  Needs the balloon hardware and firmware tree.
- **Real AP / `ndsctl`** — still needed for the `ETH-01` open question; not part
  of the balloon decisions.

## Order

| Order | Experiment | Unblocks | Effort | Hardware |
|---|---|---|---|---|
| 1 | E-BYPASS | D1 | 2–3 d | no |
| 2 | E-SELECTOR | D1 | 1–2 d | no |
| 3 | E-TWOKEY | D2 | 1–2 d | no |
| 4 | E-CRASH | D3 | 2–3 d | no |
| 5 | E-EXPIRY | D3 | 2 d | no |
| 6 | E-OUTAGE | D3 | 2 d | no |
| 7 | E-LORA | D4 | 1–2 d | no |
| 8 | E-INTERMITTENT | D3/D4 | 2 d | no |
| 9 | E-BIND | D2/D3 | 1 d | no |
| 10 | E-FEATURES | D5 | 1–2 d | no |
| — | E-MINT / E-MICROFIPS | D4/D5 | weeks | yes |

## Definition of done

For each experiment:

- [ ] Raw output is in `results/<ID>-<date>.md`, with version, rev and commands.
- [ ] The measurement table is filled in.
- [ ] The decision rule is applied in one sentence.
- [ ] The decision table at the top of this note is updated.
- [ ] Open questions are moved to `CHECKLIST.md` if they need follow-up.
- [ ] No FIPS PR or issue was opened; any FIPS finding stays out of band.

## What would change the current leanings

- **E-BYPASS shows bypass:** per-node L2 gating is insufficient in redundant
  meshes; the balloon must be a verified cut vertex, or gating must be at the
  endpoints or every hop.
- **E-SELECTOR shows drift:** bent-pipe allow-lists are fragile; terminate FIPS
  at the balloon.
- **E-TWOKEY shows same-key double-credit:** fleet keys are out unless journals
  sync; per-balloon keys become mandatory.
- **E-CRASH shows any double-credit:** offline acceptance needs a stronger
  journal (atomic commit, secure element, or online check) and a smaller cap.
- **E-EXPIRY shows a short usable window:** offline acceptance is only viable
  for short flights or small amounts.
- **E-LORA shows time-to-pay exceeds a pass:** R2 fails at the required token
  sizes; pre-load larger chunks or move to R3 on the ground.
- **E-INTERMITTENT shows credit lost on a gap:** replace link-scoped sessions
  with long-lived prepaid accounts and a dormant state.
- **E-FEATURES shows no hook:** the balloon cannot be the tollgate in flight
  firmware; gate at the ground station and treat the balloon as a relay.
