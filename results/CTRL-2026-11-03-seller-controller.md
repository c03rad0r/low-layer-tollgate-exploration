# Result: CTRL — the seller controller pauses and resumes from session state

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** controller-driven capstone (no hand-written step sequence)
- **Node(s):** `lt-pause-a`, `lt-pause-b`, `lt-pause-c`
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local patches (a)/(b)
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **TollGate commit:** n/a
- **Repo commit:** controller commit
- **Status:** pass, n=3

## Question

Can the seller loop itself decide when to pause and resume, instead of a host
script calling the gate in a fixed order? This is the product shape: session
state in, gate actions out.

## Setup

Same A–B–C chain as PD. `SellerController` owns the gate; the host only sends
traffic and credits verified payments. B's control socket is reached through
`fipsctl` inside its container (`DockerControl`).

```sh
harness/pause/run-controller-demo.sh
```

Sequence:

1. **Unpaid:** `pause()` blocks transit; A→C fails, A→B works.
2. **Payment 1:** real 50 sat P2PK+DLEQ token, verified offline; controller
   credits it and resumes.
3. **Loop:** one 1200-byte ping per tick; the controller meters and charges.
   When `Session.charge` crosses the 50 sat boundary it enters `grace` and the
   controller pauses.
4. **Payment 2:** the controller's `on_payment` resumes; A→C works again.

## Measurements

| Run | Unpaid A→C | Unpaid A→B | Ticks to grace | State | Paused A→C | Paused A→B | Used / 50,000 msat | Renew actions | A→C after renew | Evicted |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fail | pass | 11 | grace | fail | pass | 50,650 | `resume` | pass | no |
| 2 | fail | pass | 9 | grace | fail | pass | 50,549 | `resume` | pass | no |
| 3 | fail | pass | 3 | grace | fail | pass | 50,026 | `resume` | pass | no |

| Metric | Result |
|---|---|
| Unpaid transit blocked, link kept | 3/3 |
| Grace triggers one `pause:transit-blocked` | 3/3 |
| Paused A→C fails, A→B works | 3/3 |
| Overshoot at exhaustion | 26–650 msat over 50,000 (0.05–1.3 %) |
| Payment resumes forwarding | 3/3 |
| Eviction | never (payment arrived inside grace) |

## Interpretation

1. **The loop replaces the hand-written sequence.** Nothing in the harness tells
   the gate when to pause; the session state does. The observed actions were
   exactly `pause:transit-blocked` and then `resume`.
2. **Admission is not pause.** An early run used `deny()` for `unpaid`; A→C
   still passed because admission only gates new handshakes and the link was
   already up. `unpaid` must use `pause()` (transit blocked) or a full evict.
   This is now documented in `docs/0013`.
3. **Metering freezes correctly.** The controller advances the baseline without
   charging while paused; after resume only new bytes are billed. The per-peer
   policy-drop delta is subtracted in the same window.
4. **Overshoot is now tick-sized.** One ping per tick, so the boundary is
   crossed by at most one measurement step: 0.05–1.3 % in these runs, versus
   11.6 % in the Phase 1 demo (40-packet batches) and 2.18× in the first
   attempt.
5. **Eviction stayed untested here.** Payment arrived inside grace every run, so
   the durable-evict branch was exercised only by unit tests. PD covers the
   cut/re-admit variant with a prepaid token.

## Caveats

- One buyer, one chain, three runs.
- The first attempt at run 3 failed in `mint-token.sh` (transient); the retry
  passed. Not a controller failure.
- Payment is out of band; the controller sees only the credited amount.
- `gate.evict` durability still needs the ACL store; this demo never evicts.

## Follow-ups

- [ ] Force eviction in the lab (no second payment inside grace) and confirm the
      controller's evict is durable and once.
- [ ] Persist session state so the loop survives a seller restart.
- [ ] Multi-peer controller (one instance per session) with a shared meter.
- [ ] Run the loop over TCP and Ethernet.

## Artefacts

- `sidecar/tollgate_fips/controller.py`
- `sidecar/tests/test_controller.py`
- `harness/pause/controller_demo.py`, `run-controller-demo.sh`
- `docs/0013-seller-controller.md`
