# 0016 — The settlement drain

Status: implemented in `sidecar/tollgate_fips/drain.py`; 5 tests and a lab run
(`results/DRAIN-2026-11-03-daemon.md`).

## What it does

```python
daemon = SettlementDaemon(vault, worker, poll_seconds=30, batch_size=10)
daemon.run(stop=lambda: shutting_down)
```

Each pass:

1. `settle_vault_batch(vault, batch_size)` — redeem pending tokens and close
   their journal rows (BATCH behaviour: one swap per batch);
2. on progress, reset the interval to `poll_seconds`;
3. on refusal, double the interval up to `max_backoff_seconds`;
4. sleep the current interval and repeat.

The first pass runs immediately. An empty vault is a successful pass and resets
the backoff, so an idle seller polls at the normal interval, not the cap.

## Why backoff

A mint can be down, rate-limiting, or refusing a token it says is spent. Retrying
at full rate makes an outage worse and fills logs. The cap bounds recovery delay
while keeping pressure off the mint.

## Stop conditions

`run(stop=..., max_passes=...)` returns when either is satisfied. Both are
checked between passes, never inside a swap, so a stop cannot leave a half-settled
batch: the batch either completes and marks rows, or raises before marking.

## What it does not do

- **Dead-letter.** A token that never settles is retried forever at the cap.
  A production seller should count attempts and surface the row for manual
  reconcile (`reconcile_spent`) after a threshold.
- **Health.** No last-pass timestamp or metric is exported yet.
- **Concurrency.** One daemon per vault. Two would double-redeem the same token
  (the vault is not claimed/locked); run one per process and one process per
  vault.
- **The redeem→settle crash window.** A crash after the mint accepts a swap but
  before the journal commits leaves a pending row whose token is spent. That
  must reconcile as SPENT, not re-credit.

## Tests

`sidecar/tests/test_drain.py`: one pass drains and resets backoff; failures
double the backoff up to the cap; `max_passes` bounds the loop; the stop
predicate ends it; invalid intervals are refused.
