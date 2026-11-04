# 0013 — The seller controller

Status: implemented in `sidecar/tollgate_fips/controller.py`; 13 unit tests and a
controller-driven capstone (`results/CTRL-2026-11-03-seller-controller.md`).
Optional L0 frame-gate blocking is wired to eviction
(`docs/0017-frame-gate-module.md`).

## What it is

The demos drive the gate step by step from a host script. A real seller runs a
loop instead:

```text
tick():
  session.tick()                  # deadlines, grace, eviction
  paid    -> resume forwarding if paused
  grace   -> pause forwarding (transit blocked, link kept)
  evicted -> durable evict, then an optional L0 frame block
  paid    -> meter, charge; pause when the charge crosses the boundary
```

`SellerController` owns that ordering. It does not verify money and does not
talk to the mint; `on_payment(amount_msat)` is the hook a verified
`PaymentGate` receipt calls.

## Metering freeze

While the session is not `paid`, the controller advances its counter baseline
**without charging**. That is the correct form of "freeze metering on pause": a
paused peer's refused transit is not billed when it resumes, and no retrospective
charge appears. It also subtracts the per-peer policy-drop delta for the same
window (`meter.delta(policy_previous=..., policy_current=...)`), which covers
frames dropped between ticks.

## Ordering rules

- **Resume before charge.** A tick that follows a payment reopens forwarding
  first, so the same tick can also bill the traffic that arrives after the
  resume.
- **Charge, then pause.** Exhaustion happens inside `Session.charge`; the
  controller notices the state change and pauses immediately, once.
- **Eviction is once and durable.** `gate.evict` is called on the first evicted
  tick only; later ticks do not repeat it.
- **L0 block follows eviction.** If a `FrameGate` and the session's MAC were
  supplied, `frame_gate.block(mac)` runs only after `gate.evict` returns. The
  link gate stays the authorisation boundary; dropping at L0 first would
  destroy the evidence an `unpaid`/`grace` session needs to resume. A block
  failure is reported as `frame-block-failed` and does not undo the eviction.
- **Payment after eviction is refused.** The caller must re-admit and start a
  new session; `on_payment` raises `ControllerError`.

## Admission vs pause

An important distinction the capstone made obvious: `gate.deny` (runtime
admission) only gates **new handshakes**. It does not stop an established link's
transit. The `unpaid` state therefore uses `pause()` (transit blocked, link
kept), not `deny()`. `deny()`/`evict()` are for closing the link entirely.

## API

```python
from tollgate_fips.controller import SellerController, ControllerConfig

controller = SellerController(gate, session,
                              ControllerConfig(rate_bytes_per_msat=Decimal("1")))
controller.tick()                       # one loop iteration
controller.on_payment(Decimal("50000")) # verified receipt
controller.paused, controller.evicted

# Optional Ethernet L0 gate: block the device after a durable eviction.
controller = SellerController(gate, session, frame_gate=gate_l0,
                              mac="02:00:00:00:00:0a")
controller.unblock_frame()              # on re-admission, then a new session
```

`run_until(gate, session, stop, config)` is a convenience loop for lab scripts.

## Tests

`sidecar/tests/test_controller.py` covers: the first tick only establishes the
baseline; paid ticks charge the delta; exhaustion pauses once; paused bytes are
not billed after resume; the policy-drop delta is subtracted; an absolute
deadline pauses; eviction is durable and once; payment after eviction is
refused; eviction blocks the source MAC at L0 only after the durable evict;
a block failure is reported without undoing it; `frame_gate` needs a MAC;
`unblock_frame` clears the block.

## Limits

- One peer per controller instance. A multi-peer seller runs one per session.
- No persistence: the session object is in memory. Restart recovery is the
  journal/exposure layer's job, not this loop's.
- Payment is still out of band; the controller only sees the credited amount.
- `gate.evict` requires an ACL store for durability; with only the runtime
  override, eviction is not restart-durable.
- The L0 block is opt-in and Ethernet-only: the controller must be given a
  `FrameGate` and the session's source MAC. UDP/TCP/Tor/BLE sessions have no
  MAC to block, and the frame gate is rate/abuse control, not authorisation.
- A frame block is not persisted by the controller. After a restart, re-apply
  it from the durable deny list if the seller wants L0 drop to outlive the
  process.
