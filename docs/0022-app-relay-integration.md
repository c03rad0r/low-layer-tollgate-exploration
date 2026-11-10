# 0022 — App-relay integration milestone and follow-up checklist

This is the controlled next step after `docs/0019-balloon-decision-experiments.md`
and `docs/0020-balloon-production-readiness.md`. It connects the host
persistence/payment pieces into a **real request-path relay controller** without
pretending that an application-level handler is a universal mesh gate.

The previous production-direction commits include PR #3. This milestone is a
separate integration slice to be reviewed on top of those modules.

## Delivered in this slice

- [x] `CrcNullifierJournal` acts as the `NullifierJournal` interface, so
      `PaymentGate` and `SettlementWorker` can use the CRC record format directly.
- [x] `AppRelayController` (`sidecar/tollgate_fips/relay.py`) binds the caller's
      authenticated npub and current authenticated link to the prepaid account.
- [x] `accept_payment` verifies each proof via `PaymentGate`, which reserves
      exposure and the nullifier **before** the account receives credit.
- [x] Duplicate presentation (same peer or different peer) hits
      `ReservationInFlight`; no second account credit is added.
- [x] `forward_frame` uses whole-frame size and the configured byte/msat rate;
      unpaid/unknown/grace frames return `allowed=False`.
- [x] Exhaustion goes to grace. A genuine top-up resumes without erasing use.
- [x] Dormant account resume preserves credit/usage across new link ids and
      separate store reopenings.
- [x] `Sidecar/tests/test_relay.py` verifies forwarding, unpaid denial, replay,
      exhaustion, top-up, dormant resume, identity mismatch, and stale recovery.
- [x] `harness/exp-account/relay_demo.py` demonstrates the entire controller path
      with inspectable JSON output.
- [x] `results/RELAY-2026-11-10-host-relay-integration.md` records measurements.

The decision returned by `forward_frame` must be enforced by the caller. It is
not a license for unrestricted mesh forwarding, and it does not make a remote
FIPS route the paid route solely because one account has credit.

## Next integration, not done

- [ ] Replace the demo structural verifier with the real DLEQ + NUT-11 + cached-keyset verifier.
- [ ] Bind `accept_payment` to a real FIPS request handler that derives npub and
      `link_id` from authenticated FIPS connections rather than caller strings.
- [ ] Define stable offline OFFER/PAY/ACK/request/reject formats, including
      opaque correlation ids that are not used for replay decisions.
- [ ] Event handling:
      `link_up` rebind, `link_down` → `mark_link_down`, controller `tick`,
      payer-account persistence and periodic status reporting.
- [ ] Require caller-provided FMP-frame boundaries; separate any session/payload
      bytes from the wire-frame count. L0 policy drops must remain unbilled.
- [ ] Bind actual offline cached-mint vectors through this controller, including
      unknown keysets, keyset expiry/rotation and reclaim-bearing NUT-11 conditions.
- [ ] Return typed replay/rejected/exhausted/expired outcomes to the relay handler.
- [ ] Batch/reconcile settlement of the CRC-backed vault without losing the
      redeem→SETTLED window or releasing exposure prematurely.
- [ ] Add concurrent-writer policy and operational caps for account count,
      offline balance, stored nullifiers and request rate.
- [ ] Complete direct FIPS application traffic acceptance over a test net,
      not only in-process controller calls.
- [ ] Test replayed frames after a **paid** link disappears, then resumes from
      the same payer and from a different presenting peer.

## Hardware and release gates remain open

- [ ] Controller integration into the actual `balloon-fresh` relay path and
      reconciliation of its ADR-016 implementation choice.
- [ ] Bounded embedded journal wear/compaction, error-recovery and flash usage.
- [ ] Power-cut behavior at reserve→credit and redeem→settle transitions.
- [ ] Real radio-window timing and correct last-ACK/retry sequencing.
- [ ] Device key provisioning, expiry policy, key rotation/revocation.
- [ ] Signed build, rollback/disable, operator alerts, recovery runbook.
- [ ] Pilot with one mint, one verified relay path, small measured caps.

**Verdict for this milestone:** the narrow relay policy works on the host and
its persistence/replay accounting is independently tested. Production release
still requires the real verifier/FIPS transport integration and the hardware
release gate, not more unvalidated extension of the protocol surface.
