# Result: DEADLETTER — a mint outage parks the token, recovery settles it

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** dead-letter and recovery in the settlement drain
- **Node(s):** local T14; Nutshell mint `lt-mint`
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **FIPS version / rev:** n/a
- **TollGate commit:** n/a
- **Repo commit:** settlement-polish commit
- **Status:** pass

## Question

A background drain retries on backoff, but some failures are not transient. If
the mint is down for longer than the backoff cap, or refuses a token forever,
the loop retries it at full rate until an operator notices. Can the drain bound
the attempts, park the token in a durable **dead letter**, expose enough health
to see it, and still settle the money after the cause is fixed?

## Setup

```sh
harness/mint/run-deadletter-demo.sh
```

1. Mint a 10 sat P2PK token to the seller (2 proofs), verify it offline, and
   accept it into the vault: 2 journal rows RESERVED, 10,000 msat exposure.
2. Close and reopen all three databases (simulated crash), so the daemon has
   no in-memory receipts.
3. Point the drain at an unreachable mint (`http://lt-mint:9999`) for
   `max_attempts = 3` passes.
4. Inspect `health()` and the dead-letter list.
5. Requeue the rows, swap in the real redeemer, run one pass.
6. Check the journal, exposure, vault and NUT-07.

The failure is an explicit connection refusal from a real HTTP request, not a
simulated return value: `ConnectError: [Errno 111] Connection refused`.

## Raw output

```
before:
  vault_pending 2
  exposure_msat 10000
  journal       RESERVED, RESERVED

outage (after 3 passes):
  pending          0
  dead_lettered    2
  exposure_msat    10000        (unchanged: nothing settled)
  journal          RESERVED, RESERVED
  health.passes            3
  health.failed            6   (2 rows x 3 passes)
  health.consecutive_failures 3
  health.last_error        mint unreachable: ConnectError: ... Connection refused
  health.backoff_seconds   8.0  (1 -> 2 -> 4 -> 8)
  health.last_pass_at      set
  health.last_success_at   null

recovered (requeue + real mint, one pass):
  pending          0
  dead_lettered    0
  exposure_msat    0
  journal          SETTLED, SETTLED
  settled          2
  failed           0
  health.consecutive_failures 0
  health.last_error           null
  health.last_success_at      set

NUT-07: Ys 2, SPENT, SPENT, all_spent true
```

## Measurements

| Step | Result |
|---|---|
| Accepted into vault | 2 rows, 10,000 msat exposure |
| Failed passes before parking | 3 |
| Attempts recorded per row | 3 |
| Rows dead-lettered | **2** (both proofs of the token) |
| Exposure while dead-lettered | **10,000 msat** (unchanged) |
| Journal while dead-lettered | RESERVED ×2 |
| Extra passes after dead-letter | 0 redeemer calls |
| Requeue operation | 2 keys, clears attempts and dead-letter timestamp |
| Recovery pass | settled 2, failed 0 |
| Exposure after recovery | **0** |
| Journal after recovery | **SETTLED ×2** |
| NUT-07 inputs | **SPENT ×2** |

## Interpretation

1. **Dead-lettering bounds the retry cost.** After three failed passes the rows
   leave `pending()`; later drain passes do not call the mint at all. The
   daemon keeps its health counters, so the condition is visible, but it stops
   spending requests on a token that is not settling.
2. **Parking does not release money or exposure.** The journal stays RESERVED
   and the exposure stays 10,000 msat while the row is dead-lettered. This is
   the conservative direction: a token that might still be good is not written
   off, and a double spend cannot quietly consume the payer's cap.
3. **Recovery is an explicit operator action.** `requeue(key)` clears the
   attempts and the dead-letter timestamp; the next pass tries again. The demo
   then settles from the vault alone, exactly as the crash-recovery demo does.
4. **The threshold is per row, not per token.** A two-proof token produces two
   dead letters. That keeps the vault row model simple (one row per proof) and
   the health count honest about how many pieces are parked.
5. **Backoff and dead-letter are different controls.** Backoff spaces retries
   during a transient outage (1 → 2 → 4 → 8 s); the threshold stops retrying
   altogether after a persistent one. Both are needed: backoff alone never
   reaches a human, and a threshold alone would hammer the mint three times in
   quick succession.

## Caveats

- One token, one outage, one mint version, `FakeWallet`.
- The outage is an unreachable port, not a mint that accepts and then fails.
  The latter (redeem succeeds at the mint, journal write fails) is the
  redeem→settle crash window, still open.
- Dead letters are rows, not tokens. An operator UI would group them by token.
- The daemon is still single-writer; two daemons on one vault would race.
- Recovery used the same process and a swapped redeemer; a real operator would
  restart the process and point it at the restored mint.

## Follow-ups

- [ ] Dead-letter metric in the seller's health endpoint (the dict is ready).
- [ ] Group dead letters by token in the operator view.
- [ ] Reconcile a token the mint says is already spent (`reconcile_spent`)
      instead of parking it.
- [ ] Close the redeem→settle crash window by recording the redemption result.

## Artefacts

- `sidecar/tollgate_fips/drain.py` (`max_attempts`, `health`, `requeue`)
- `sidecar/tollgate_fips/vault.py` (attempt/dead-letter columns and migration)
- `sidecar/tests/test_drain.py`, `sidecar/tests/test_vault.py`
- `harness/mint/deadletter_demo.py`, `run-deadletter-demo.sh`
