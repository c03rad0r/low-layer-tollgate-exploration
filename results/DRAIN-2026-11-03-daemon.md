# Result: DRAIN — the background settlement loop

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** background drain — accept, crash, let the daemon settle
- **Node(s):** local T14; Nutshell mint `lt-mint`
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **FIPS version / rev:** n/a
- **TollGate commit:** n/a
- **Repo commit:** drain commit
- **Status:** pass

## Question

Settlement so far is a single explicit pass. A seller needs a loop: poll the
token vault, settle what it can, and back off when the mint refuses. Does the
daemon drain the vault after a restart with no in-memory receipts?

## Setup

```sh
harness/mint/run-drain-demo.sh
```

1. Mint a 10 sat P2PK token; accept it into the vault (2 proofs, 10,000 msat
   exposure).
2. Close all three databases (simulated crash).
3. Start `SettlementDaemon(vault, worker, poll_seconds=1)` and run until the
   vault is empty.
4. Check the journal, exposure and the pass/sleep counters.

## Measurements

| Metric | Value |
|---|---|
| Proofs | 2 |
| Vault before → after | **2 → 0** |
| Exposure before → after | **10,000 → 0 msat** |
| Passes | **1** |
| Settled | 2 |
| Failed | 0 |
| Fee | 1 sat |
| Sleeps | 0 (the first pass emptied the vault) |
| Journal | SETTLED ×2 |
| Errors | none |

## Interpretation

1. **The loop needs no in-memory state.** The daemon starts from reopened files
   and settles from the vault alone, so a seller restart is not a special case.
2. **The first pass runs immediately.** `sleeps` is empty because there was work
   to do; the poll interval only delays the next attempt, not the first.
3. **Backoff is for refusal, not for success.** An empty vault counts as a
   successful pass and resets the interval; a failing redemption doubles it up
   to the cap (unit-tested, five cases).
4. **Batching and draining compose.** `settle_vault_batch` is the daemon's unit
   of work, so a drain gets the 1-sat-per-batch fee behaviour from BATCH.

## Caveats

- One token, two proofs, one pass, `FakeWallet`.
- The crash is simulated by closing databases, not killing a process.
- The daemon is synchronous; a production seller should run it on its own task.
  `health()` now exposes the last pass/success/error.
- The redeem→settle window inside a pass is still untested (documented).

## Follow-ups

- [ ] Run the daemon across a real process restart and a mint outage.
- [x] Emit a metric/last-pass timestamp for health checks — `health()` in
      `results/DEADLETTER-2026-11-03.md`.
- [x] Cap total attempts and surface a dead-letter state for rows that never
      settle — `max_attempts` + dead letter in `results/DEADLETTER-2026-11-03.md`.

## Artefacts

- `sidecar/tollgate_fips/drain.py`
- `sidecar/tests/test_drain.py`
- `harness/mint/drain_demo.py`, `run-drain-demo.sh`
