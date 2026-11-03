# TIP: Session scope — `link` and `e2e`

- **Target repo:** `OpenTollGate/tollgate`
- **Status:** Draft for PR
- **Depends on:** endpoint advertisement (P1)
- **Experiment citations:** Exp A (`results/A-2026-11-03-counter-boundary.md`),
  PD (`results/PD-2026-11-03-pause-payment.md`), 01-TCP
  (`results/01-tcp-2026-11-03.md`), Exp I (planned),
  buyer-role design (`docs/0005-buyer-role.md`)

## Abstract

Add an explicit `scope` to an offer and to the session it creates:
`link` (one hop, metered at the FMP boundary) or `e2e` (the whole path, metered
once). Add an explicit `transport` tag. State the no-double-charge rule.

## Motivation

The current protocol is implicitly end-to-end: a payment buys access to a
service, and the path in between is not priced. A link sale is different — it
buys transit on **one hop**, and the seller's cost is the bytes that hop
carries. Without a scope field:

- a buyer cannot tell whether it is charging for a hop or for a path;
- a reseller can double-charge the same bytes on two hops and claim both were
  `link`;
- a metering implementation cannot say which counter it is supposed to read.

"Per transport" is a **policy scope**, not a place to put code. FIPS transports
are identity-blind; the npub appears at the link layer. The protocol therefore
names the scope explicitly and leaves placement to the implementation.

## Specification

### 1. Offer and session fields

An offer MAY carry:

```json
["scope", "link" | "e2e"]
["transport", "<transport>"]
```

Defaults: `scope=e2e` when absent (backwards compatible), `transport` absent
meaning "any transport the seller advertises".

A session created from an offer MUST mirror both fields. A session that does
not match its offer's `scope` or `transport` is invalid.

### 2. `scope=link`

- Covers exactly one FIPS link: one `(seller_npub, transport, remote_addr)`
  tuple, one FMP link.
- Metering boundary is the FMP frame on that link, as defined in the wire-byte
  metering TIP.
- The seller MUST be the peer at the far end of that link. A seller that only
  forwards for the link is not a `link` seller; that is `e2e`.
- The session ends when the link ends, or at `valid_until`, whichever is first.

### 3. `scope=e2e`

- Covers the path from payer to the service named by the offer.
- Metering, if any, is at the service boundary, not per hop.
- Intermediate forwarders MUST NOT open a second `link` charge for the same
  bytes.

### 4. The no-double-charge rule

For a given payer, a given byte, and a given scope, the byte MUST be charged at
most once.

Concretely:

- A `link` session on hop A and a `link` session on hop B are **different**
  scopes-of-accounting even though both say `link`. Charging both is correct:
  two hops, two costs.
- A `link` session and an `e2e` session covering the same bytes are a double
  charge. Implementations MUST NOT create both for the same flow.
- An `e2e` offer MUST NOT require a `link` session between the same two peers.

The distinction is per **(payer, hop, scope)**, not per literal string. Two
sellers on two hops are two hops; one seller charging twice is a violation.

### 5. Resale

A node MAY be a payer on one link and a seller on another. See
`docs/0005-buyer-role.md`. Additional requirements:

- The downstream session's `transport` is the downstream link's transport, not
  the upstream one.
- Downstream unsettled credit SHOULD be bounded by upstream prepaid remaining,
  less a reserve. This is policy, not a wire field, but implementations that
  resell MUST document their bound.
- `seller_npub == payer_npub` MUST be rejected.

### 6. Metering interaction

`scope=link` uses the wire-byte rule. `scope=e2e` is out of scope for the
wire-byte TIP except to say that it MUST NOT be metered with the link rule.

## Backwards compatibility

- Absent `scope` means `e2e`, which is today's behaviour.
- Absent `transport` means "any", which is today's behaviour.
- Existing sessions remain valid; they are `e2e` with unknown transport.

## Security considerations

- Scope is a claim by the seller. A client cannot verify that a `link` seller
  is really the far end of the link without checking the FMP peer identity;
  clients SHOULD do so where the transport exposes it.
- A malicious reseller can label an `e2e` flow as `link` to charge twice. The
  rule above makes that a protocol violation, but detection is social unless
  the client can see the path. This is a known limitation; the exposure cap
  bounds the damage.

## Citation

- Why the boundary is the FMP frame: Exp A,
  `results/A-2026-11-03-counter-boundary.md`, `docs/0002-metering-boundary.md`.
- Resale and double-charge: `docs/0005-buyer-role.md`.
- Multi-transport reconciliation: Exp I (planned).
- Link-scope pause and payment path: `results/PD-2026-11-03-pause-payment.md`.
- TCP transport: `results/01-tcp-2026-11-03.md`.
