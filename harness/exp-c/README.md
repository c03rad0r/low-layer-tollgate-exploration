# Exp C — cut and re-admit

Two FIPS nodes (`seller`, `buyer`) on a private Docker bridge, with the sidecar
mounted read-only at `/opt/sidecar`.

## What it measures

1. **Exp B in the lab:** ACL reload latency on FIPS 0.6.0-dev.
2. **Exp C:** the cost of the only exhaustion lever — `fipsctl disconnect` —
   and whether the in-band path (the payment lane, if payment rides the link)
   survives the cut.
3. **Re-admit:** how long from an ACL allow to a usable link, including the
   handshake and a fresh `link_id`.

The two nodes use the `fips-test:latest` image built from the pinned upstream
tree. The topology is a single UDP peer link. No mint, no funds.

## Run

```sh
harness/exp-c/run-admission.sh        # runtime admission vs the ACL tick
harness/exp-c/run-exp-c.sh            # leave containers up
harness/exp-c/run-exp-c.sh --down     # tear down afterwards
harness/exp-c/repeat.sh 3             # clean run, repeat, summarise
```

The script brings the compose project up and runs `exp_c.py` on the host (it
talks to each container with `docker exec`). `repeat.sh` tears the project down
between runs, saves each log under `/tmp/opencode/`, and prints ranges plus a
`summary.json`. The recorded run is `results/C-2026-11-03-cut-readmit.md`.

## Identities

Both nsecs are derived from the test mesh name `low-layer-tollgate-exp-c` with
the upstream `derive_keys.py`. They are test keys, not secrets. See
`configs/`.

## Expected result

On FIPS 0.6.0-dev there is no per-peer forwarding role, so strict `pause()`
raises. The crude fallback is a **durable eviction**: deny the npub, wait for
the ACL, then disconnect.

- A bare `disconnect` is undone by `auto_connect` in 6.5–6.9 s, with a new
  `link_id` and no new payment.
- Deny → wait → disconnect holds (3 s test, no link).
- Re-admission costs 2.7–2.9 s (0.75–0.83 s ACL + 1.87–2.08 s link, n=4).

That is the evidence for patch (b) and P4.
