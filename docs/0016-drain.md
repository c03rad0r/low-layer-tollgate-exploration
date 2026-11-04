# 0016 — The settlement drain

Status: implemented in `sidecar/tollgate_fips/drain.py`; 8 tests and two lab
runs (`results/DRAIN-2026-11-03-daemon.md`,
`results/DEADLETTER-2026-11-03.md`).

## What it does

```python
daemon = SettlementDaemon(vault, worker, poll_seconds=30, batch_size=10,
                          max_attempts=10)
daemon.run(stop=lambda: shutting_down)
```

Each pass:

1. `settle_vault_batch(vault, batch_size)` — redeem pending tokens and close
   their journal rows (BATCH behaviour: one swap per batch);
2. record one attempt for every row whose token failed;
3. after `max_attempts`, park those rows in the dead letter;
4. on progress (or nothing to do), reset the interval to `poll_seconds`;
5. on refusal with no progress, double the interval up to
   `max_backoff_seconds`;
6. sleep the current interval and repeat.

The first pass runs immediately. An empty vault is a successful pass and resets
the backoff, so an idle seller polls at the normal interval, not the cap.

## Why backoff

A mint can be down, rate-limiting, or refusing a token it says is spent. Retrying
at full rate makes an outage worse and fills logs. The cap bounds recovery delay
while keeping pressure off the mint.

## Dead letters

Backoff spaces retries; it never stops them. A persistent failure (a long
outage, a token the mint will not accept) would otherwise be retried forever.

`max_attempts` bounds that: each failed row gets an attempt count in the vault,
and once the count reaches the threshold the row gets a `dead_lettered_at`
timestamp. Dead-lettered rows are excluded from `pending()`, so later passes do
not call the mint for them. The journal stays RESERVED and the exposure stays
outstanding — parking a row must not release money or free the payer's cap.

Recovery is explicit:

```python
for entry in daemon.dead_letters():
    daemon.requeue(entry.vault_key)   # clear attempts + timestamp
```

The next pass retries. If the mint says the token was already spent, the
operator should use `reconcile_spent` instead of requeueing.

The threshold is per **row** (one row per proof), so a two-proof token parks
two rows. That keeps the vault model simple; an operator view should group by
token.

## Health

`daemon.health()` returns a `DrainHealth` (also `.as_dict()`):

| Field | Meaning |
|---|---|
| `passes`, `settled`, `failed`, `fee_sat` | lifetime counters since start |
| `last_pass_at` | wall-clock time of the last pass |
| `last_success_at` | wall-clock time of the last pass with a settlement |
| `last_error` | last redeemer error, cleared by a successful pass |
| `consecutive_failures` | passes with failures and no progress |
| `pending`, `dead_lettered` | current vault row counts |
| `backoff_seconds`, `max_attempts` | current policy |

This is the surface a health endpoint or control socket should expose. It is
deliberately a plain dataclass, not a metrics dependency.

## Stop conditions

`run(stop=..., max_passes=...)` returns when either is satisfied. Both are
checked between passes, never inside a swap, so a stop cannot leave a half-settled
batch: the batch either completes and marks rows, or raises before marking.

## What it does not do

- **Concurrency.** One daemon per vault. Two would double-redeem the same token
  (the vault is not claimed/locked); run one per process and one process per
  vault.
- **The redeem→settle crash window.** A crash after the mint accepts a swap but
  before the journal commits leaves a pending row whose token is spent. That
  must reconcile as SPENT, not re-credit.
- **Automatic reconcile.** A dead letter is parked, not classified. An operator
  (or a future worker) decides between requeue and `reconcile_spent`.
- **Grouping.** Dead letters are rows; the operator view must group by token.

## Tests

`sidecar/tests/test_drain.py`: one pass drains and resets backoff; failures
double the backoff up to the cap; `max_passes` bounds the loop; the stop
predicate ends it; invalid intervals/attempts are refused; a persistent failure
dead-letters after `max_attempts` and is not retried, then requeues and settles;
`health()` records last pass/success/error; an empty vault resets the backoff.

`sidecar/tests/test_vault.py`: attempts and dead-letter timestamps, exclusion
from `pending()`, requeue, settled rows unaffected, counts, and in-place
migration of an old vault schema.
