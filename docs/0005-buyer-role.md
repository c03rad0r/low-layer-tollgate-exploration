# 0005 — The buyer role: reselling transit

Status: design. Evidence pending Phase 1 (Exp C, H) and Phase 6.

## Why a buyer exists

A link gate prices *transit*: bytes carried for someone else. Not every
participant wants to be a seller of last resort, and not every participant can
reach a seller directly. The natural middle is a **buyer** — a node that buys a
bulk allotment at one price and resells smaller allotments to peers that cannot
or will not buy from the original seller.

This is not a new role invented for the protocol. It falls out of the same
mechanics once `scope` and `transport` are explicit:

- A buyer holds a *link session* with its upstream seller.
- It offers *downstream* link sessions to its own neighbours.
- The two are different `(seller_npub, scope, transport)` tuples and must be
  accounted separately.

## Scope

| Field | Upstream (buyer → seller) | Downstream (neighbour → buyer) |
|---|---|---|
| `scope` | `link` | `link` |
| `transport` | the transport the buyer uses | the transport the neighbour uses |
| Metering boundary | buyer's link with the seller | neighbour's link with the buyer |
| Who is charged | the neighbour (via the buyer) | the neighbour |

`scope=e2e` is the degenerate case: the buyer is a pure forwarder and the
original payer's session covers the whole path. Link-scoped resale is the
interesting case because each hop is independently metered and independently
paid.

## The double-charging rule

A byte MUST NOT be charged twice **for the same scope on the same hop**.

- If a neighbour buys `scope=link` from the buyer, the buyer charges the
  neighbour for bytes on the neighbour→buyer link.
- The buyer's own upstream session meters the *same bytes again* on the
  buyer→seller link, because that is a different hop, a different link, and a
  different cost (the buyer's uplink).
- If the neighbour buys `scope=e2e`, the buyer MUST NOT open a second
  link-scoped charge for those bytes.

The spec must say this explicitly. It is the one place where "per transport"
and "per hop" can be confused, and the confusion produces either free transit
or a double bill.

## Price ladder and margin

The buyer publishes its own advertisement. Nothing in the protocol forces a
margin, but a buyer that resells below its own cost is a subsidy, not a
business. The advertisement SHOULD carry the buyer's rate; the buyer's own
upstream rate is its private cost basis.

Hysteresis is required. If the buyer re-prices on every upstream change, every
downstream peer sees churn. The `link_cost` input (patch (c)) exists so that a
price change is a *slow* signal, not a per-tick oscillation.

## Identity and credit

The buyer is an npub like any other. It has:

- its own FIPS static key and therefore its own npub;
- its own journal for downstream payments;
- an exposure cap for downstream peers, independent of its upstream cap.

Downstream credit is **not** backed by upstream credit. A buyer must not lend
more downstream than it can absorb if an upstream session is cut. The safe rule
is:

```
downstream_unsettled <= upstream_prepaid_remaining * (1 - reserve)
```

with `reserve` covering the buyer's own traffic and the settlement window. This
is a policy number, not a protocol field, but the spec SHOULD name the
constraint so implementations do not silently overcommit.

## Failure modes

| Failure | Effect | Mitigation |
|---|---|---|
| Upstream cuts the buyer | downstream peers lose transit | `grace` + `retry_after`; buffer in the buyer |
| Buyer disappears owing downstream credit | downstream peers lose prepaid value | downstream journal settles independently; cap |
| Buyer re-prices on every tick | churn, route flaps | hysteresis on `link_cost` |
| Buyer resells `scope=e2e` as `scope=link` | double charge | explicit scope rule above |
| Buyer is also a seller to itself | accounting loop | reject `seller_npub == payer_npub` |

## What this means for the gate

The gate interface does not need a separate "buyer" verb. A buyer is just a
node that is simultaneously a payer on one link and a seller on another. The
only additions are:

1. `scope` and `transport` in the session, so the two directions are
   distinguishable;
2. an accounting rule that forbids double-charging the same scope on the same
   hop;
3. a downstream exposure bound tied to upstream prepaid balance.

Everything else is the same state machine as `0004`.

## Experiment

`experiments/05-buyer-role/` will run a three-node chain — seller → buyer →
neighbour — and check that:

- the buyer's upstream counter and the neighbour's downstream counter agree on
  frame bytes for the same traffic;
- the neighbour's charge is not duplicated on the upstream session for
  `scope=e2e`;
- cutting the upstream link produces `grace` at the buyer and `retry_after` at
  the neighbour, not a silent black hole.

That experiment is Phase 2+ because it needs the sidecar gate and pause
semantics. It is recorded here so the spec drafts do not accidentally define a
protocol that cannot express resale.
