# 0021 — Prepaid npub accounts and the flight-journal prototype

## Why a second account type?

`Session` models the short, link-scoped TollGate session used by the earlier
demos. `PrepaidAccount` is the additional contract for intermittent relays:
**the paid asset is an account bound to an authenticated FIPS npub, not the
current link**. It is deliberately distinct from `Session`, which remains
unchanged for the earlier link-demonstrator controllers.

`PrepaidAccount` does not speak Cashu or modify a forwarding table by itself. Its
callers must authenticate the peer, perform payment verification, persist the
correct state transition, then enforce it in a real relay's handler or transit
forwarding path.

## Account API

From `sidecar/tollgate_fips/account.py`:

| Call | Behavior |
|---|---|
| `top_up(amount_msat)` | Adds balance without resetting usage. Rejected for evicted accounts. |
| `charge(frame_bytes)` | Applies `frame_bytes / rate` as Decimal cost, only when `forwarding_allowed`. Crosses exhaustion into grace. |
| `link_down()` | Becomes DORMANT and forgets the current link id; retains reserved balance and resume state. |
| `link_up(payer_npub, new_link_id)` | Restores dormant state, but only if the presenting npub owns the account. Dormant credit alone never forwards. |
| `tick(now)` | Applies optional absolute deadline/grace. Link silence is not eviction. |
| `evict(reason)` | Explicit seller action; ordinary contact loss must not use this as a shortcut. |

`forwarding_allowed` requires both `state == PAID` and an active authenticated
link id. The measurement step determines allowed overshoot; the module does not
make a fake precise reconciliation claim.

### Persistence

`PrepaidAccountStore(path)` uses WAL and `synchronous=FULL`. Save after any
transition that affects money or authorization. Credit, use and rate are
serialized as strings and restored as `Decimal`; no float accumulation.

```python
accounts = PrepaidAccountStore(path)
account = accounts.get_or_create(peer_npub, rate_bytes_per_msat=1)
account.top_up(10000)
account.link_up(peer_npub, current_link_id)
account.charge(1230)
account.link_down()
accounts.save(account)
accounts.close()
```

Across a separate process the same npub returns DORMANT credit. `link_up` with a
mismatched npub raises `IdentityMismatch`, not a fresh allowance.

The reference monotonic deadline continues across **process** restarts on the
same bootable system. Whole-machine RTC durability and flight-safe clock
fallback are explicit open work in the readiness plan; this module is not an
RTC proof.

## Strict offline NUT-11 policy

`check_offline_condition(condition, seller_pubkey, final_expiry, window, now)`
from `nut11.py` accepts only an exact one-of-one lock to the compressed public
key and a non-overdue keyset admission window:

- **accepted:** data equals that compressed key; `sigflag` absent or
  `SIG_INPUTS`.
- **rejected:** wrong key, missing/malformed shape, `refund`, `locktime`,
  `pubkeys`, `n_sigs`, grouped signing, unknown extension fields/tags, or a
  keyset expiring inside the stated settlement window.

This is deliberately conservative for offline acceptance rather than a full
Cashu implementation. DLEQ/signature checks and proof nullifiers are separate;
this function is not a substitute for either. Standard Cashu issuance that
includes a locktime will therefore need a compatible no-reclaim/offline offer;
it should not be silently accepted after stripping tags.

## Append-only journal prototype

`CrcJournal` is a single-writer reference for embedded deferred settlement:

```text
FJNL | version | framed-state | uint16 JSON-length | canonical JSON | crc32(JSON)
```

Valid keys are `(mint_url, unit, keyset_id, nullifier)`. The note amount is
stored as a string, preserving integer/decimal amounts. The journal provides:

- `reserve(...)` before granting credit.
- `settle(...)` after confirmed redemption.
- `mark_spent(key)` after a lost/mint-spent lookup.
- `recover_at_open=True` to turn stale reservations into SPENT.
- `pending()` containing only the latest **unredeemed** state per key.
- Compaction by latest key state with CRC validation before atomic replacement.

A short/incomplete final header or record is truncated safely. Invalid CRC,
magic, object shape or an unexpected framing/status mismatch is a hard error,
not silent open access. This distinction is important: a torn last record can be
retried by the payer, while mid-file corruption must not be turned into free
service.

## Acceptance boundaries

This work is directly reusable on the host, but it does **not** establish:

- per-peer authenticated FIPS policy inside a specific relay controller;
- no_std compilation or ESP32 flash atomicity;
- phone/power-loss durability of a particular embedded log format;
- transaction durability under two concurrent writers;
a formal interoperable offer/payment protocol;

`CrcNullifierJournal` adapts the bounded record journal to the existing
`PaymentGate`/`SettlementWorker` abstraction. `AppRelayController` then adds
lookup/binding of a caller-authenticated FIPS npub and link to the prepaid
account, and charges whole FMP frames only when the account is online and in
`PAID`. Its real FIPS event loop and real DLEQ adapter remain pending work.

- an exact accounting/per-frame-class counter implementation.

The checklist in `docs/0020-balloon-production-readiness.md` tracks those gates
independently from prototype unit tests.
