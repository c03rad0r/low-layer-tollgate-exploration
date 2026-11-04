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
(`results/01-tcp-2026-11-03.md`). Ethernet is done too: beacon discovery,
metering, runtime admission, and pause on a dual-homed A–B–C chain
(`results/01-ethernet-2026-11-03.md`, `results/PE-2026-11-03-pause-ethernet.md`).
BLE and Tor are not started.

**Exit:** the same state-machine log and counter reconciliation on all four.
The Ethernet demo includes the beacon advertisement path; BLE uses
`mark_verified` as its payer hook.

## Phase 3 — Local mint + receiver spent journal (2–3 weeks)

Self-issued ecash, durable nullifier journal, P2PK to the seller, exposure
caps, batched settlement.

Status: the journal core is implemented (`sidecar/tollgate_fips/journal.py`,
13 tests, `docs/0009`): RESERVED → SETTLED | SPENT, WAL + `synchronous=FULL`,
crash recovery treats old reservations as SPENT, and the keyset admission
predicate uses `final_expiry` as a settlement deadline. Settlement is implemented: a `SettlementWorker` redeems the accepted P2PK token
at the mint, then sets the journal SETTLED and releases the exposure
(`results/SETTLE-2026-11-03-redeem.md`), and four tokens settle in one swap
(1 sat versus ~4; `results/BATCH-2026-11-03.md`). A `SettlementDaemon`
drains the vault on a timer with exponential backoff, bounds retries with a
durable dead letter, and exposes `health()`
(`results/DRAIN-2026-11-03-daemon.md`, `results/DEADLETTER-2026-11-03.md`). The exposure cap is
implemented (`sidecar/tollgate_fips/exposure.py`, 10 tests, `docs/0010`): per
payer/mint/unit, reserved before the journal row so a crash overstates rather
than understates. `PaymentGate` orders verifier → exposure → journal and
returns a receipt (`sidecar/tollgate_fips/payment.py`, 8 tests, `docs/0011`).
A real Nutshell 0.21.0 `FakeWallet` mint runs in `harness/mint/`; a 50 sat
P2PK+DLEQ token verifies offline with the mint stopped
(`results/F-2026-11-03-offline-verify.md`). The verified proofs also run through
`PaymentGate`/journal/exposure; a second process refuses the replay and
settlement clears the exposure. The verifier is still a lab script; FIPS session
continuity remains. Exp G is done: Nutshell still accepts a spend after
`final_expiry`, so the receiver predicate is the only guard
(`results/G-2026-11-03-final-expiry.md`).

- **F** — keep paying with the mint stopped.
- **G** — what happens after keyset `final_expiry`?

**Exit:** a full session with the mint process killed; no double spend
accepted after a receiver restart; exposure never exceeds the cap.

## Phase 4 — FIPS changes (local patches, out-of-band conversation)

- (a) runtime admission mutation over the control socket — **implemented**
- (b) per-peer forwarding role — **the pause enabler**, implemented
- (c) price input into `link_cost`, with hysteresis — **implemented**

Status: (b) is implemented locally and passes an A–B–C chain test
(`patches/0001-per-peer-forwarding.patch`, result `PB-2026-11-03`): transit from
a blocked peer is dropped while its link, Noise session and local path stay.
(a) is implemented too: runtime admission saves 0.86–1.40 s per re-admission
(`results/A2-2026-11-03-runtime-admission.md`). (c) is implemented as a local
`set_price` multiplier: a 1.0 penalty moved a diamond leaf's parent in
351–513 ms with routing intact, while 0.05 stayed inside hysteresis
(`results/PRICE-2026-11-03-local-cost.md`). The sidecar's
`FipsGate.pause()`/`resume()` use `set_forwarding` via `UnixControl` and were
validated against the patched seller. A seller controller now drives the loop from session state
(`sidecar/tollgate_fips/controller.py`, `results/CTRL-2026-11-03-seller-controller.md`).
The capstone (`results/PD-2026-11-03-pause-payment.md`) runs unpaid → paid →
exhaust → pause → renew on the patched chain with real ecash and no disconnect:
A→C is blocked while A→B and the link survive; the link id is preserved. Six
runs (3 UDP, 3 TCP) all preserve the link and resume on it, and policy-dropped
bytes are attributed per peer and excluded from billing. The patch is unmerged;
no public FIPS interaction.

**Exit:** patches that make `grace` implementable; Exp C and H evidence
attached; a Signal write-up prepared, not sent.

## Phase 5 — Spec PRs (`OpenTollGate/tollgate`)

P1 endpoint advertisement + port removal · P2 scope · P3 wire-byte metering ·
P4 pause and renewal.

Status: all four drafts are written and cite the latest results; P4 now cites
PB/PD and the patched forwarding role. No PR has been opened. See
`spec-drafts/README.md` for branch/title/evidence mapping.

**Exit:** four PRs, each citing experiment IDs and linking its result file.

## Phase 6 — Channels and fungibility

Replace discrete tokens with `cdk-spilman` behind the same interface. Evaluate
Granola-style cross-mint swaps as a **treasury** path, not a gate path.

**Exit:** channel path working; measured cross-mint time-to-admit, with a
gate/no-gate recommendation.

## Phase 7 — Frame gate

nft `netdev` chain on `ether type 0x2121` with an authorised-MAC set, wired to
the module; 802.1X / OWE / per-client VLAN evaluated as the stronger option.

- **E2** drop cost at 1k/10k/100k pps — done: lossless at ~99k pps,
  CPU inconclusive (`results/E2-2026-11-03-frame-gate-throughput.md`)
- **E3** does 802.11s association alone pass frames?
- **E4** per-MAC token bucket: nft vs tc/BPF — done: per-MAC and identical
  in effect; nft is the smallest
  (`results/E4-2026-11-03-per-mac-token-bucket.md`)
- **FrameGate module** — nft rule/set driven from Python, real-tool demo
  (`docs/0017-frame-gate-module.md`,
  `results/FRAMEGATE-2026-11-03-module.md`)

**Exit:** unauthorised MACs cannot put `0x2121` frames on the link at line
rate, and the doc says plainly that this is rate control, not authorisation.
