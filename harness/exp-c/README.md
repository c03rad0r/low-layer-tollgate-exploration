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
harness/exp-c/run-exp-c.sh
```

The script brings the compose project up, runs `exp_c.py` on the host (it talks
to each container with `docker exec`), writes the raw log to
`results/C-<date>.md`, and leaves the containers up for inspection unless
`--down` is passed.

## Identities

Both nsecs are derived from the test mesh name `low-layer-tollgate-exp-c` with
the upstream `derive_keys.py`. They are test keys, not secrets. See
`configs/`.

## Expected failure

On FIPS 0.6.0-dev there is no per-peer forwarding role, so `pause()` raises.
The crude fallback disconnects: the link, the FIPS IPv6 path and any payment
traffic that rode it all die. Re-admission needs a new handshake and, with ACL
strict mode, a file write that lands on the next 1 s tick. The numbers are the
evidence for patch (b) and P4.
