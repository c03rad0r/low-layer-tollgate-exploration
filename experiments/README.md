# Experiments

One directory per experiment. Each has a `README.md` with the question, the
topology, the exact commands, and the pass/fail criterion. Raw results go in
`../results/<id>-<date>.md` **before** anything is summarised.

| Dir | Question | Phase | Status |
|---|---|---|---|
| `01-tcp/` | Can a link session be sold, metered and torn down over TCP? | 2 | cut/re-admit done; payment/beacon pending |
| `02-tor/` | Does the same gate work when the transport address is `127.0.0.1`? | 2 | not started |
| `03-ethernet/` | Same over EtherType `0x2121`, with a beacon advertisement? | 2 | harness ready; FIPS pair pending |
| `04-ble/` | Same over BLE, using `mark_verified` as the payer hook? | 2 | not started |
| `05-buyer-role/` | Can a node buy upstream and resell downstream without double-charging? | 2/6 | not started |
| `06-local-mint/` | Can a session continue with the mint stopped, and what happens at `final_expiry`? | 3 | not started |
| `07-frame-gate/` | Can nft `netdev` gate `0x2121` at line rate, and is it authorisation? | 7 | nft correctness done; AP/rate pending |

## Shared rules

- Every run records FIPS version + rev, node names, and the exact commands.
- No mainnet funds. Test mints only.
- `df -h` before writing to a fleet node.
- Both sides' counters are recorded. A result that only has the seller's
  counter is incomplete.
- The same acceptance test is used across transports:

  1. link up, session `unpaid`;
  2. payment accepted, session `paid`;
  3. traffic until exhaustion, session `grace`;
  4. renewal, session `paid`;
  5. exhaustion + grace deadline, session `evicted`;
  6. buyer and seller byte counters reconcile within tolerance.

## Phase 0 results (already run)

- **A** — counter boundary: `../results/A-2026-11-03-counter-boundary.md`
- **B** — ACL reload latency: `../results/B-2026-11-03-acl-latency.md`
- **E** — captive-portal bypass: blocked, no Ethernet transport on the fleet.
