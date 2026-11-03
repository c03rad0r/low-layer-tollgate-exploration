# 0008 — The gate interface: `admit / deny / meter / pause / evict`

Status: Phase 1 interface. Implemented in `sidecar/tollgate_fips/`.

This is the contract the sidecar exposes to a transport demo. It is deliberately
small, and it is written so that the one missing FIPS hook cannot be hidden.

## The five verbs

| Verb | Meaning | Precondition | Postcondition |
|---|---|---|---|
| `admit(npub)` | allow this peer to join the link | session is `unpaid` or `evicted` | peer is in the ACL; session `unpaid`; payment lane open |
| `deny(npub)` | refuse this peer at admission | — | peer is denied; no link is registered |
| `meter(npub)` | read the seller's counters for this peer | link exists | `MeterReading` with in/out/total FMP frame bytes |
| `pause(npub)` | stop chargeable forwarding, keep link and Noise session | session is `paid` or `grace` | forwarding blocked; payment lane open |
| `evict(npub)` | deny the npub, wait for the ACL, close the link | session is `grace` and its deadline passed | npub denied; link closed; session `evicted` |

`admit` and `deny` are idempotent. `meter` is read-only and monotonic per link.
`pause` is the verb FIPS cannot implement today; see below.

## Types

```
SessionState = unpaid | paid | grace | evicted

MeterReading:
  npub, link_ids
  bytes_in, bytes_out, bytes_total      # FMP frame bytes, per direction
  packets_in, packets_out
  rate_bytes_per_msat                   # from the offer
  cost_msat                             # bytes_total / rate

Notice:
  code = payment-required | session-exhausted | payment-due
  level, session_id, retry_after, top_up
```

`cost_msat` uses `Decimal`, not float. A rate is **bytes per millisat**; a
smaller rate means a higher price per byte. See P3.

The frame that crosses the exhaustion boundary may push `used_msat` past
`allotment_msat` by up to one frame. The seller absorbs that overshoot. It is
the unavoidable cost of not being able to pause mid-frame, and it should be
stated in the offer rather than discovered at settlement.

## Pause is not implemented by FIPS

FIPS 0.5.x and 0.6.x offer only:

- ACL admission at L1, and
- `fipsctl disconnect` at L2.

There is no per-peer forwarding role, so `pause` cannot be honoured. The
interface therefore has two modes:

- **strict (default):** `pause()` raises `PauseUnsupported`. The caller must
  decide whether to `evict` or to keep serving unpaid.
- **crude (`--allow-disconnect`):** `pause()` is implemented as a **durable**
  `evict()` (deny, wait, disconnect), and the caller is told that the payment
  lane died. This is the Phase 1 demo, and its failure is the evidence for FIPS
  patch (b) and spec PR P4.

A gate MUST NOT report `grace` while having closed the link. If it disconnects,
the state is `evicted`.

## Eviction must be durable

`evict` is **deny → wait for the ACL to be effective → disconnect**, not a bare
`disconnect`.

Exp C measured the difference on a passive seller with an `auto_connect`
buyer:

- a bare `disconnect` was undone by `auto_connect` in **6.6–6.8 s**, with a new
  `link_id` and no new payment;
- deny → wait → disconnect held for the full 3 s test, and re-admission cost
  **2.7 s** (0.83 s ACL + 1.87 s link).

`FipsGate.evict()` implements the durable sequence. It raises if no ACL store is
configured rather than silently doing a non-durable cut. `pause()` in crude mode
calls it. See `results/C-2026-11-03-cut-readmit.md`.

## Metering source

`meter()` merges:

- `fipsctl show peers` — `npub` ↔ `link_id` and per-link `stats`;
- `fipsctl show links` — `link_id` ↔ `transport_id`, `remote_addr`,
  `transport_type`;
- `fipsctl show transports` — optional, for the unattributed transport delta.

The per-link counters are FMP frame bytes at the transport API (Exp A). They are
aggregate and include control frames; the reading MUST be labelled `all_frames`
until a per-class counter exists.

## Failure policy

| Failure | Policy |
|---|---|
| control socket unreachable, **new** admission | fail closed: do not admit |
| control socket unreachable, **existing** paid session | do not evict; retry; a transient read error is not non-payment |
| meter returns a smaller counter than the previous sample | treat as a reset (link re-created); start a new epoch, do not refund or double-charge |
| `disconnect` fails | retry with backoff; mark `evict_pending`, not `evicted` |
| ACL write fails | fail closed for admission; never report a link as admitted |

## Trust boundary

The seller reads its **own** daemon. The npub comes from the FIPS peer table,
which is the proven identity after the Noise handshake. The buyer's counters are
never used for billing; they are only for reconciliation, and disagreement is a
`pause` (or `grace`) trigger.

The frame gate (`docs/0006`) is not part of this interface. It is rate control,
not authorisation.

## Mapping to the spec

| Verb | Spec |
|---|---|
| `admit` / `deny` | L1 admission, `scope=link` (P2) |
| `meter` | wire-byte metering (P3) |
| `pause` / `evict` | four-state session machine (P4) |

## Non-goals

- This interface does not price a service. It prices a link.
- It does not implement payment verification; that is `docs/0003` and Phase 3.
- It does not resell. A buyer is two instances of this interface, one paying and
  one selling (`docs/0005`).
