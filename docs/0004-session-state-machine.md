# 0004 — Session state machine: pause, do not drop

Status: design, with MONAD as prior art. Evidence needed: Exp C (Phase 1).

## The problem

A link gate that disconnects at exhaustion also kills the payment lane. That
is the chicken-and-egg this whole design starts with: you cannot pay over a
link you are not admitted to, and on Ethernet and BLE there is no IP fallback.

## Prior art

MONAD (Cashu Spilman channels over onion-style routing) already solved this:

- sessions start **paused by default**;
- `CONNECT` is rejected before the first payment;
- during later pauses, `CONNECT` is accepted but **forwarding is blocked until
  payment**;
- underpayment stays paused until the balance is positive;
- eviction is a separate, advisory event (`ChannelEvicted`, scoped `session` or
  `relay`), not the same thing as running out.

TollGate should adopt the shape, not the implementation.

## The four states

| State | Seller behaviour | Signal |
|---|---|---|
| `unpaid` | admitted, chargeable forwarding blocked, payment lane open | `21023 level=info code=payment-required` |
| `paid` | forwarding allowed, metering | — (session event is the receipt) |
| `grace` | forwarding blocked, lane open, link and Noise session kept | `21023 level=error code=session-exhausted` |
| `evicted` | link closed and npub denied | ACL deny, then FIPS `Disconnect`, reason *resource exhaustion* |

Transitions: `unpaid → paid` on accepted payment; `paid → grace` at allotment
exhaustion; `grace → paid` on renewal; `grace → evicted` after `grace` expires.

**Eviction must be durable.** A bare `disconnect` is not `evicted`: with
`auto_connect` the peer re-establishes the link in 6.5–6.9 s, with a new
`link_id` and no new payment (Exp C). The seller MUST deny the npub, wait until the ACL
reports the deny effective, and only then disconnect. Re-admission then costs
ACL latency plus a handshake (2.7–2.9 s in the lab).

## Notices

Reuse `kind:21023`. Add:

- `["retry_after","<secs>"]` — when to try again;
- `["top_up","<steps>"]` — the smallest useful purchase;
- `["session_id","<id>"]` — correlate with the session event.

Rules: idempotent; rate-limited to at most one per 10 seconds; may be sent
before any session exists.

Renewal uses the same vocabulary: `payment-due` at 80–90 % is the early edge of
the same machine, not a separate event kind.

## Expiry

Sessions carry `["issued_at"]` and `["valid_until"]`. FIPS has no time sync, so
absolute time is advisory only. The gate enforces:

```
deadline = min(valid_until, received_at + max_session_duration + skew_tolerance)
```

and a monotonic local timer is the authority. `valid_until` is the cross-check
that lets a restarted seller reconstruct the state.

Keyset `final_expiry` is **not** the session clock. See NUT-02 and
`spec-drafts/04-pause-and-renewal.md`:
after `final_expiry` the mint may "irrevocably remove all of the nullifiers"
(NUT-02), so it is a *settlement* deadline. Admission must reject proofs whose
keyset expires before `now + settlement_window`, and `valid_until` must not
exceed `final_expiry − settlement_window`.

## Dependency on FIPS

`grace` requires blocking forwarding for one peer while keeping the link. FIPS
has no such hook today: the only levers are admit/deny at L1 and `disconnect`
at L2. Patch (b) — a per-peer forwarding role consulted on the data path — is
what makes this implementable.

Until (b) lands, Phase 1's demo uses `disconnect` and documents the failure.
That failure is the argument for (b).
