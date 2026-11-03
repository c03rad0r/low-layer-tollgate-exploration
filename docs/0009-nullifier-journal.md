# 0009 — The durable nullifier journal

Status: Phase 3 core implemented in `sidecar/tollgate_fips/journal.py`; 13 journal
tests. Not yet wired to a mint or to a payment proof.

## The gap it closes

NUT-11 P2PK proves a token is locked to the seller, and DLEQ proves the mint
signed it. Neither proves the token has not been spent. The only unspentness
source is NUT-07 `/checkstate`, which is a round trip. If the seller accepts a
proof before the mint confirms it, a replay is possible.

The journal makes the receiver's own record authoritative for the one thing it
can know locally: **this receiver has already accepted this nullifier**. It does
not prove the token is unspent at the mint; that is settlement. It bounds the
replay window to the first acceptance.

## State machine

```
RESERVED --settle()--> SETTLED
RESERVED --mark_spent()--> SPENT
SETTLED  --mark_spent()--> SPENT
```

- **RESERVED** — written and committed *before* the seller grants credit. The
  seller is now exposed for this amount until settlement.
- **SETTLED** — the mint accepted the proof. The exposure is closed.
- **SPENT** — a double spend or an unrecoverable reservation. The nullifier is
  refused forever.

A duplicate `reserve()` raises by state: `ReservationInFlight` for RESERVED,
`AlreadySettled` for SETTLED, `AlreadySpent` for SPENT. A replay is never a
silent succeed.

## Key

```sql
PRIMARY KEY (mint_url, unit, keyset_id, nullifier)
```

- `keyset_id` is part of the key because NUT-02 nullifiers are keyset-scoped.
- `unit` separates sat and msat.
- `mint_url` separates trust domains even when a nullifier string collides.

## Durability ordering

`reserve()` opens `BEGIN IMMEDIATE`, inserts, and commits. The connection runs
`journal_mode=WAL` and `synchronous=FULL`. The commit returns before credit is
granted.

The failure modes are deliberately asymmetric:

| Crash point | Result |
|---|---|
| before `reserve` commits | no credit, no journal row; the buyer can retry |
| after `reserve` commits, before credit | a RESERVED row with no service; the seller may have lost a sale, never a replay |
| after credit, before `settle` | a RESERVED row; recovery treats it as SPENT (conservative) |

`recover_stale_reservations(older_than_seconds)` marks old RESERVED rows SPENT.
It never re-credits. The operator can reconcile a row by hand; the protocol does
not guess.

## `final_expiry` is a settlement deadline

NUT-02 says that after `final_expiry` the mint may "irrevocably remove all of the
nullifiers". That makes `final_expiry` a settlement deadline, not a session
clock.

Admission predicate:

```python
keyset_admissible(final_expiry, settlement_window_secs, now)
    == final_expiry is None or final_expiry >= now + settlement_window_secs
```

Reject a proof whose keyset expires inside the settlement window. Session
`valid_until` must not exceed `final_expiry − settlement_window`. The session's
local monotonic deadline remains the authority for `grace`/`evicted`
(`docs/0004`).

## What it does not solve

- **Cross-seller double spend.** A token given to two sellers is invisible to
  both journals until one settles. That is bounded by the per-peer, per-mint
  exposure cap (`docs/0003`), not by the journal.
- **Forgery.** The journal stores what the verifier accepted. It does not check
  the mint signature or the P2PK lock.
- **Settlement.** `settle()` is a local state change; the mint call is the
  caller's job. A background settlement worker is the next piece.
- **Mint deletion after `final_expiry`.** The journal is the surviving record;
  it does not recover value the mint has already deleted.

## API

```python
from tollgate_fips.journal import NullifierJournal, keyset_admissible

with NullifierJournal("/var/lib/tollgate/journal.sqlite3") as journal:
    res = journal.reserve(
        mint_url="https://mint.example",
        unit="sat",
        keyset_id="009a1f...",
        nullifier="ab" * 32,
        amount_msat="1.5",
        final_expiry=2_000_000_000,
    )
    # grant credit here, only after reserve() returned
    ...
    journal.settle(res)          # after NUT-07 confirms
```

## Tests

```
PYTHONPATH=sidecar python3 -m unittest discover -s sidecar/tests -v
```

Journal cases: reserve/settle, duplicate RESERVED, SETTLED and SPENT replays,
reopen persistence, a second connection, keyset/mint/unit key separation, exact
`Decimal` amounts, stale recovery, and the keyset admission predicate.

## Next

- A local test mint in `harness/mint/`.
- P2PK-to-seller proof verification feeding `reserve()`.
- A settlement worker with NUT-07, batched.
- Exposure caps and Exp F (mint stopped) / Exp G (`final_expiry`).
