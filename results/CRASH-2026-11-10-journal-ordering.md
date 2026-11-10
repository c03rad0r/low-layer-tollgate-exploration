# Result: CRASH — reserve-before-credit is what prevents double credit

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-CRASH (docs/0019, decision D3)
- **Stack:** local Python sidecar `NullifierJournal`, SQLite WAL with
  `synchronous=FULL`
- **Status:** completed, n=20 per arm plus 120 truncation offsets

## Question

Does the nullifier journal survive a process crash without double-credit?
Does the ordering matter, or is durability alone enough?

## Setup

Each arm starts a fresh journal in a child process, exits using `os._exit(17)`,
then reopens the database and tries to reserve the same nullifier again. A credit
flag models the forwarding grant; `double_credit = credit_before_crash AND
replay_accepted`. Twenty runs per arm.

The fourth arm deliberately reverses the ordering: write the credit flag and
crash before reserving. The final arm truncates an append-only, CRC-framed
journal log at every byte offset to test torn-record handling.

```sh
PYTHONPATH=./sidecar python3 harness/exp-crash/crash_test.py
```

## Raw output

```json
{
  "runs_per_arm": 20,
  "arms": [
    {
      "mode": "reserve_then_crash",
      "double_credit": 0,
      "replay_states": ["RESERVED"],
      "credit_before_crash": 0
    },
    {
      "mode": "reserve_credit_then_crash",
      "double_credit": 0,
      "replay_states": ["RESERVED"],
      "credit_before_crash": 20
    },
    {
      "mode": "settle_then_crash",
      "double_credit": 0,
      "replay_states": ["SETTLED"],
      "credit_before_crash": 0
    },
    {
      "mode": "buggy_credit_then_reserve",
      "double_credit": 20,
      "replay_states": ["accepted"],
      "credit_before_crash": 20
    }
  ],
  "append_log": {
    "truncations": 120,
    "invented_records": 0,
    "record_bytes": [40, 40, 40]
  }
}
```

## Interpretation

1. **Ordering is the invariant.** Reserving before the credit flag survived both
   process crashes tested, and replay was refused. Crediting first double-credited
   in 20/20 runs. SQLite durability cannot fix a policy that writes the money
   side after the forwarding side.
2. **An unsettled reservation is conservative, not free money.** A crash between
   reserve and settle does not grant a replay. The cost of that conservative
   recovery is potentially losing an unpaid credit, not giving the customer two
   grants for one token.
3. **The log-tail behavior is compatible with an embedded design.** A torn tail
   never produced an extra valid reservation. This does not measure flash wear,
   write amplification, atomicity needs, or power-fail timing on ESP32; it only
   validates the incomplete-record handling.
4. **The mint remains the settlement authority.** The crash-safe local journal
   settles double-presentation at this receiver, not unknown global spends. That
   distinction is demonstrated in `TWOKEY-2026-11-10-offline-shared-key.md`.

## Decision for D3

Keep verify → reserve (vault first) → credit, and settle asynchronously. The
offline journal is defensible against process crashes when this ordering is
strict. Do not claim the same for flash power failure until that hardware case
is measured.

## Caveats and follow-ups

- `os._exit` is a controlled process crash, not `kill -9` of a host process
  group, VM power loss or removal of ESP32 power halfway through a flash erase.
- One writer per journal. Concurrent writers are outside this experiment.
- Follow-up: repeat on a flash-backed append-only log under real power cut, and
  fault-inject after the mint accepts a redemption but before local settlement.

## Artefacts

- `harness/exp-crash/crash_test.py`.
- `sidecar/tollgate_fips/journal.py` (unchanged by the experiment).
