# TIP: Pause and renewal — the four-state session

- **Target repo:** `OpenTollGate/tollgate`
- **Status:** Draft for PR. **Held until Exp C produces numbers.**
- **Depends on:** scope (P2), wire-byte metering (P3)
- **Experiment citations:** Exp C (planned, Phase 1),
  `docs/0007-current-enforcement.md`, `docs/0004-session-state-machine.md`
- **Prior art:** MONAD (Cashu Spilman channels over onion routing)

## Abstract

Replace "cut the link at exhaustion" with a four-state session machine:
`unpaid → paid → grace → evicted`. In `unpaid` and `grace` the link and the
Noise session stay up, the payment lane stays open, and **chargeable forwarding
is blocked**. Only `evicted` closes the link.

## Motivation

A link gate that disconnects at exhaustion also kills the payment lane. That is
the chicken-and-egg the design starts from: you cannot pay over a link you are
not admitted to, and on Ethernet and BLE there is no IP fallback.

Today FIPS gives a gate only `admit` (ACL) and `disconnect`. There is no way to
pause one peer's forwarding while keeping its link. `docs/0007` records this as
the load-bearing gap; Exp C will measure the cost of the only available
workaround (cut and re-admit).

## Prior art and credit

MONAD already implements this shape:

- sessions start **paused by default**;
- `CONNECT` is refused before the first payment;
- during later pauses, `CONNECT` is accepted but **forwarding is blocked until
  payment**;
- underpayment stays paused until the balance is positive;
- eviction is a separate, advisory event (`ChannelEvicted`, scoped `session`
  or `relay`), not the same thing as running out.

This TIP adopts the shape and the vocabulary, not MONAD's channel
implementation. Credit: MONAD.

## Specification

### 1. States

| State | Link | Chargeable forwarding | Payment lane | Signal |
|---|---|---|---|---|
| `unpaid` | open | **blocked** | open | `21023`, `level=info`, `code=payment-required` |
| `paid` | open | allowed, metered | open | — (session event is the receipt) |
| `grace` | open | **blocked** | open | `21023`, `level=error`, `code=session-exhausted` |
| `evicted` | closed | — | closed | FIPS `Disconnect`, reason *resource exhaustion* |

"Chargeable forwarding blocked" means the seller does not forward the
customer's session-layer traffic. Control traffic needed to keep the link, the
MMP session and the payment lane alive MUST continue.

### 2. Transitions

```
unpaid --accepted payment--> paid
paid   --allotment exhausted--> grace
grace  --renewal--> paid
grace  --grace deadline--> evicted
```

- `unpaid → evicted` MAY happen after a stated admission timeout.
- `paid → evicted` MUST NOT happen on exhaustion; it goes through `grace`.
- A renewal in `grace` returns to `paid` without a new link.

### 3. Notices

Reuse `kind:21023`. Add:

```json
["retry_after", "<seconds>"]
["top_up", "<steps>"]
["session_id", "<id>"]
```

- `retry_after`: when the client may try again.
- `top_up`: the smallest useful purchase, in steps.
- `session_id`: correlates the notice with the session event.

Rules:

- idempotent — a repeated notice MUST NOT create a second session;
- rate-limited to at most one per 10 seconds per session;
- MAY be sent before a session exists (the `unpaid` case);
- MUST NOT be the only record of state; the session event is authoritative.

`payment-due` at 80–90 % of allotment is the early edge of the same machine, not
a separate event kind. Implementations SHOULD send it with the same tags.

### 4. Expiry

Sessions carry `["issued_at"]` and `["valid_until"]`.

FIPS has no time synchronisation, so absolute time is advisory. The seller
enforces:

```
deadline = min(valid_until, received_at + max_session_duration + skew_tolerance)
```

and a **monotonic local timer** is the authority. `valid_until` is the
cross-check that lets a restarted seller reconstruct state.

Keyset `final_expiry` is **not** the session clock. NUT-02 says that after
`final_expiry` the mint may "irrevocably remove all of the nullifiers", so it is
a **settlement deadline**:

- admission MUST reject proofs whose keyset expires before
  `now + settlement_window`;
- `valid_until` MUST NOT exceed `final_expiry − settlement_window`.

### 5. Implementation requirement on FIPS

`grace` requires blocking forwarding for one peer while keeping its link. FIPS
has no such hook today. This TIP therefore depends on a **per-peer forwarding
role** consulted on the data path (patch (b) in the exploration repo).

Until that exists, an implementation that claims this TIP MUST either:

- implement the role in its own forwarding layer, or
- declare itself non-conformant and fall back to `disconnect`.

It MUST NOT silently disconnect and call the state `grace`.

### 6. Reconciliation is a pause trigger

If the buyer's and seller's byte counters disagree beyond a stated tolerance,
the seller SHOULD enter `grace` rather than continue billing. Pausing is
reversible; a disputed invoice is not.

## Backwards compatibility

- Sellers that do not implement this TIP continue to disconnect at exhaustion.
  Clients see the existing behaviour.
- `21023` notices are additive; unknown tags MUST be ignored.
- No change to the payment format.

## Security considerations

- A paused peer still occupies a link slot and a Noise session. Sellers MUST
  bound the number of paused sessions and the grace duration, or `grace`
  becomes a free-rental DoS.
- A `retry_after` in the past or an absurd `top_up` is a client-side input; the
  client MUST validate.
- Pausing is not a settlement guarantee. The seller MUST NOT credit a renewal
  it has not verified to its own satisfaction (see the payer-binding TIP).

## Experiment plan

Exp C (Phase 1, before this PR opens):

1. Establish a paid link, exhaust it.
2. Measure, with the current tooling, the time from exhaustion to
   `fipsctl disconnect` taking effect and to a fresh link being usable
   (ACL add ~1 tick, per Exp B: 756–979 ms).
3. Record whether the payment lane survives the cut. It does not; that is the
   result the TIP cites.
4. Re-run after patch (b) and show `grace` without a cut.

The PR text will cite `results/C-<date>.md` and the Exp B numbers in
`results/B-2026-11-03-acl-latency.md`.

## Citation

- Current enforcement and the missing hook: `docs/0007-current-enforcement.md`.
- State machine rationale: `docs/0004-session-state-machine.md`.
- MONAD: four-state shape, paused-by-default sessions, advisory eviction.
- Exp B: ACL changes take 756–984 ms, tick-bound; relevant to both the `unpaid`
  admission and the `evicted` teardown.
