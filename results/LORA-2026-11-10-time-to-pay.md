# Result: LORA — time-to-pay over 255-byte frames

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-LORA (docs/0019, decision D4)
- **Method:** seeded stop-and-wait fragmentation model, not RF hardware
- **Status:** completed, 1,000 model runs per token/rate

## Question

Does a Cashu payment fit into a balloon contact window at 255-byte fragments and
30% independent loss per fragment/ACK? What token sizes should the offline
service allow?

## Setup

The token byte sizes are from real P2PK+DLEQ tokens produced by the local
Nutshell wallet:

| Token | Byte size | Payload frames (255 B) |
|---|---:|---:|
| 1 proof | 541 | 3 |
| 3 proofs | 1,013 | 4 |
| 5 proofs | 1,487 | 6 |

For every fragment, transmission time is `255 * 8 / bps`; if it is delivered,
a small ACK also incurs airtime. A lost fragment or ACK retries until delivered.
Loss is 30%, seed `20261109`, 1,000 runs per cell.

```sh
python3 harness/exp-lora/lora_sim.py
```

This models conservative stop-and-wait behavior; it is not the Wirehair/FEC
scheduler from `balloon-fresh` and must not be reported as measured LoRa.

## Raw measurements

| Token | Rate | Payload frames | Median time | p95 time | Median frames sent | Expected overhead |
|---|---:|---:|---:|---:|---:|---:|
| 1 proof | 1 kbps | 3 | 12.43 s | 22.76 s | 6.0 | 2.0x |
| 3 proofs | 1 kbps | 4 | 16.58 s | 29.01 s | 8.0 | 2.0x |
| 5 proofs | 1 kbps | 6 | 24.99 s | 39.46 s | 12.0 | 2.0x |
| 1 proof | 5 kbps | 3 | 2.10 s | 4.58 s | 5.0 | 1.67x |
| 3 proofs | 5 kbps | 4 | 3.32 s | 5.42 s | 8.0 | 2.0x |
| 5 proofs | 5 kbps | 6 | 4.99 s | 7.88 s | 12.0 | 2.0x |
| 1 proof | 22 kbps | 3 | 0.57 s | 1.03 s | 6.0 | 2.0x |
| 3 proofs | 22 kbps | 4 | 0.76 s | 1.23 s | 8.0 | 2.0x |
| 5 proofs | 22 kbps | 6 | 1.13 s | 1.79 s | 12.0 | 2.0x |

p95 as a fraction of the theoretical contact window at 1 kbps:

| Token | 1 minute | 5 minutes | 30 minutes |
|---|---:|---:|---:|
| 1 proof | 37.9% | 7.6% | 1.3% |
| 3 proofs | 48.4% | 9.7% | 1.6% |
| 5 proofs | 65.8% | 13.2% | 2.2% |

## Interpretation

1. **P2PK note transfers are small enough for pre-planned contact windows.**
   Even the five-proof token takes p95 39.46 s at 1 kbps; at 5 kbps it is below
   8 s, and at 22 kbps below 2 s. No local mint is required merely because a
   token is "large" compared with one frame.
2. **Retransmission, not serialization, dominates much of the budget.** The
   median sends about 2 fragments per delivered fragment/ACK exchange in the
   conservative model. Erasure coding and stronger application-level retries
   can change this substantially.
3. **The retry behavior must be idempotent.** A lost final ACK will tempt a
   payer to present the same token again. A proof-keyed nullifier journal rejects
   a duplicate presentation instead of granting more credit; `CRASH` and `BIND`
   exercise that behavior.
4. **Preload larger offline credit rather than spending every few seconds.**
   Continuous micro-payments are poor radio economics: the useful offline unit
   should cover several passes or an entire flight, bounded by the exposure cap.

## Decision for D4

Use R2 (preloaded notes locked to the particular relay's compressed P2PK key)
as the baseline for the balloon. A local mint (R3) is not justified by payment
message size alone. R3's remaining argument is a ground-side, completely offline
payer; that is a separate trust and resource choice, not a necessity shown here.

If passes are seconds rather than minutes, or loss is much worse than 30%, the
offer must shrink proof counts or give more advance credit.

## Caveats and follow-ups

- This is a model. There was no LR2021, antenna, airtime scheduler or real
  30–37% loss measurement.
- Independent loss, fixed 255-byte fragments and one ACK per fragment;
  no FMP overhead, forward-error coding, congestion, hidden-node collisions,
  reassembly retransmission ordering, or duty-cycle constraint.
- Offline Cashu verification was not benchmarked on embedded
  hardware; timing here is transport only.
- Follow-ups: repeat with the actual Wirehair scheme and LR2021 on the bench,
  and test recovery after a lost final ACK with a real P2PK token.

## Artefacts

- `harness/exp-lora/lora_sim.py`.
- Result tokens were created only from the local `FakeWallet` test mint.
