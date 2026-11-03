# Roadmap

Each phase has an exit criterion that is a *measurement*, not a feeling. If an
experiment invalidates an assumption, update `docs/` and this file in the same
commit.

## Phase 0 — Seams (1 week)

Confirm F1–F4 from the plan, and run the three experiments that can invalidate
the design.

Status: A and B are done. The nft half of E is done on `veth`; the `ndsctl` half
is blocked on a real AP.

- **A** — do FIPS counters count frame bytes or payload bytes?
- **B** — how fast does a peer ACL change take effect?
- **E** — does `ndsctl` deauthorisation stop EtherType `0x2121` frames?

**Exit:** `docs/0007-current-enforcement.md` states, with raw output, exactly
what a gate can enforce today with zero patches.

## Phase 1 — Sidecar, zero FIPS changes (2–3 weeks)

`tollgate-fips`: a control-socket client that admits (ACL files), meters
(`fipsctl show links` / `show peers`), and evicts (`disconnect`).

Status: the interface (`docs/0008`), the meter/session core, durable eviction,
ACL writes and 32 unit tests are in `sidecar/`. The meter has run read-only
against `host-b` (`results/S-2026-11-03-sidecar-meter.md`). Exp C is done on
a two-node lab (`results/C-2026-11-03-cut-readmit.md`): a bare disconnect is
undone by `auto_connect` in 6.5–6.9 s; deny + wait + disconnect holds, and
re-admission costs 2.7–2.9 s (n=4). Exp H shows ACL-deny re-parents a
three-node triangle in 109 ms, with one link of churn and sticky parent choice
(`results/H-2026-11-03-reparent.md`). The Phase 1 demo now uses real offline
ecash: unpaid traffic rode free for 14,274 B, a durable eviction stopped it,
and a prepaid re-admission cost ≈1.75 s
(`results/DEMO-2026-11-03-buyer-exhausts.md`). The pause itself is still
missing; that is patch (b).

- **C** — cost of cut and re-admit; does the payment lane survive?
- **H** — can ACL-deny force re-parenting, and how much churn?

**Exit:** a demo where a buyer exhausts, is cut, and must re-pay; both sides'
counters reconcile to the byte; the absence of pause semantics is documented
as the reason the demo is crude.

## Phase 2 — Four transports (parallel, ~2 weeks each)

TCP → Ethernet → BLE → Tor, all behind the same gate interface.

Status: the cut/re-admit acceptance test passes over TCP
(`results/01-tcp-2026-11-03.md`). Ethernet, BLE and Tor are not started.

**Exit:** the same state-machine log and counter reconciliation on all four.
The Ethernet demo includes the beacon advertisement path; BLE uses
`mark_verified` as its payer hook.

## Phase 3 — Local mint + receiver spent journal (2–3 weeks)

Self-issued ecash, durable nullifier journal, P2PK to the seller, exposure
caps, batched settlement.

Status: the journal core is implemented (`sidecar/tollgate_fips/journal.py`,
13 tests, `docs/0009`): RESERVED → SETTLED | SPENT, WAL + `synchronous=FULL`,
crash recovery treats old reservations as SPENT, and the keyset admission
predicate uses `final_expiry` as a settlement deadline. The exposure cap is
implemented (`sidecar/tollgate_fips/exposure.py`, 10 tests, `docs/0010`): per
payer/mint/unit, reserved before the journal row so a crash overstates rather
than understates. `PaymentGate` orders verifier → exposure → journal and
returns a receipt (`sidecar/tollgate_fips/payment.py`, 8 tests, `docs/0011`).
A real Nutshell 0.21.0 `FakeWallet` mint runs in `harness/mint/`; a 50 sat
P2PK+DLEQ token verifies offline with the mint stopped
(`results/F-2026-11-03-offline-verify.md`). The verified proofs also run through
`PaymentGate`/journal/exposure; a second process refuses the replay and
settlement clears the exposure. The verifier is still a lab script; FIPS session
continuity and Exp G remain.

- **F** — keep paying with the mint stopped.
- **G** — what happens after keyset `final_expiry`?

**Exit:** a full session with the mint process killed; no double spend
accepted after a receiver restart; exposure never exceeds the cap.

## Phase 4 — FIPS changes (local patches, out-of-band conversation)

- (a) runtime admission mutation over the control socket
- (b) per-peer forwarding role — **the pause enabler**
- (c) price input into `link_cost`, with hysteresis

**Exit:** patches that make `grace` implementable; Exp C and H evidence
attached; a Signal write-up prepared, not sent.

## Phase 5 — Spec PRs (`OpenTollGate/tollgate`)

P1 endpoint advertisement + port removal · P2 scope · P3 wire-byte metering ·
P4 pause and renewal.

**Exit:** four PRs, each citing experiment IDs and linking its result file.

## Phase 6 — Channels and fungibility

Replace discrete tokens with `cdk-spilman` behind the same interface. Evaluate
Granola-style cross-mint swaps as a **treasury** path, not a gate path.

**Exit:** channel path working; measured cross-mint time-to-admit, with a
gate/no-gate recommendation.

## Phase 7 — Frame gate

nft `netdev` chain on `ether type 0x2121` with an authorised-MAC set, wired to
the module; 802.1X / OWE / per-client VLAN evaluated as the stronger option.

- **E2** drop cost at 1k/10k/100k pps
- **E3** does 802.11s association alone pass frames?
- **E4** per-MAC token bucket: nft vs tc/eBPF

**Exit:** unauthorised MACs cannot put `0x2121` frames on the link at line
rate, and the doc says plainly that this is rate control, not authorisation.
