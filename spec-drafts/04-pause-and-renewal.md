# TIP: Pause and renewal — the four-state session

- **Target repo:** `OpenTollGate/tollgate`
- **Status:** Draft for PR. Exp C, PB, PD and MP produced numbers; PR not
  opened.
- **Depends on:** scope (P2), wire-byte metering (P3)
- **Experiment citations:** Exp C (`results/C-2026-11-03-cut-readmit.md`),
  PB (`results/PB-2026-11-03-per-peer-forwarding.md`), PD
  (`results/PD-2026-11-03-pause-payment.md`), MP
  (`results/MP-2026-11-03-multi-peer-isolation.md`), Exp B
  (`results/B-2026-11-03-acl-latency.md`), `docs/0007-current-enforcement.md`,
  `docs/0004-session-state-machine.md`
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
| `evicted` | closed, npub denied | — | closed | ACL deny, then FIPS `Disconnect`, reason *resource exhaustion* |

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
- `evicted` MUST be durable: deny the npub, wait until the ACL reports the
  deny effective, then disconnect. A bare `disconnect` is re-established by
  `auto_connect` in 6.5–6.9 s with a new `link_id` and no new payment (Exp C).

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

`grace` requires blocking forwarding for one peer while keeping its link.
Upstream FIPS 0.6.0-dev has no such hook. This TIP therefore depends on a
**per-peer forwarding role** consulted on the data path. A local, unmerged
patch demonstrates the hook (`0001-per-peer-forwarding.patch` in the private patches repo, result
`PB-2026-11-03`): transit from the peer is dropped while local delivery, the
link and the Noise session stay.

Until that exists, an implementation that claims this TIP MUST either:

- implement the role in its own forwarding layer, or
- declare itself non-conformant and fall back to **durable eviction** (deny,
  wait for the ACL, then disconnect).

It MUST NOT silently disconnect and call the state `grace`. It also MUST NOT
call a bare `disconnect` `evicted` when `auto_connect` can undo it. With the
forwarding role, `grace` can be implemented without a cut; without it, the
implementation is non-conformant and must say so.

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

## Experiment results

Two-node UDP lab, FIPS `0.6.0-dev` (`2ba790b`), passive seller, `auto_connect`
buyer, strict ACL.

| Path | Result |
|---|---|
| Bare `disconnect` | link back in **6.5–6.9 s**, new `link_id`, no payment |
| Deny → wait → disconnect | held for 3 s, no link on either side |
| ACL effective | 0.8–1.0 s (Exp B: 756–984 ms, tick-bound) |
| Re-admission | **2.7–2.9 s** total (n=4) |
| Unpaid with patch (b) | A→C blocked; A→B and link preserved |
| Pause at exhaustion | A→C blocked; link id preserved; no disconnect |
| Renewal | second token; resume restores A→C on the same link |
| Repeatability | 3/3 UDP and 3/3 TCP; link id preserved every run |
| Blocked transit billing | excluded via per-peer `policy_blocked_by_peer` |
| Ethernet pause | A→C blocked, A→B and link kept, 3/3 (`PE-2026-11-03`) |
| In-band path during cut | fails; returns on reconnect, without payment |
| Unpaid link, Phase 1 demo | **14,274 bytes forwarded for 0 msat** |
| Prepaid re-admit | **≈1.75 s** (677 ms ACL + 1,077 ms link) |

This is why the TIP separates `grace` from `evicted`: the only lever today is
a durable cut, and it costs the payment lane. The Phase 1 demo also measured
the failure directly: with the link up and the session `unpaid`, 14,274 bytes
were forwarded for 0 msat. Patch (b) is still required to make `grace`
implementable, and to make `unpaid` enforceable without a cut. The full raw output is in
`results/C-2026-11-03-cut-readmit.md`.

Patch (b) (`results/PB-2026-11-03-per-peer-forwarding.md`) implements the
forwarding role locally: transit from a blocked peer is dropped while local
delivery and the link stay. The capstone
(`results/PD-2026-11-03-pause-payment.md`) runs the full sequence on an A–B–C
chain with real offline ecash: unpaid blocked, payment restores transit,
exhaustion pauses with the link id preserved, and a second payment resumes. No
disconnect is issued.

MP repeats the block on a four-node star where B has three peers. Blocking A
drops A→D while C→D, A→B and the A–B link stay up, and `policy_blocked_by_peer`
grows under A only, n=3 (`results/MP-2026-11-03-multi-peer-isolation.md`). A
single-client test could not distinguish a per-peer block from a node-wide one;
this one can.

The patch is local and unmerged; the upstream FIPS ask is out of band. The TIP
can require the role and cite the lab evidence.

## Citation

- Current enforcement and the missing hook: `docs/0007-current-enforcement.md`.
- State machine rationale: `docs/0004-session-state-machine.md`.
- MONAD: four-state shape, paused-by-default sessions, advisory eviction.
- Exp B: ACL changes take 756–984 ms, tick-bound; relevant to both the `unpaid`
  admission and the `evicted` teardown.
- Exp C: a bare `disconnect` is undone by `auto_connect` in 6.5–6.9 s; durable
  eviction holds, and re-admission costs 2.7–2.9 s (n=4).
