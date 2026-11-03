# Result: B — ACL reload latency

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** B — how fast does a peer ACL change reach the running daemon?
- **Node(s):** `host-b`
- **FIPS version / rev:** 0.5.1
- **TollGate commit:** n/a
- **Repo commit:** `8881da6` (scaffold)
- **Status:** pass

## Question

The only runtime admission lever in FIPS 0.5.x is the peer ACL file. If a
sidecar writes `peers.allow` / `peers.deny`, how long until the running daemon
applies it? This sets the floor for Phase 1 admission and eviction, and it is
the number the pause TIP cites when it says disconnect is too blunt.

## Setup

`host-b` has passwordless sudo and `deny_all=true` with
`effective_mode=allow_then_deny_all`. The test appends a **throwaway npub** — a
valid bech32 key for which nobody holds the private key — to
`/etc/fips/peers.allow`, polls `fipsctl acl show` until the npub appears in the
effective allow set, restores the file from a backup, and polls until it
disappears.

Timer: `time.monotonic()` in the remote Python, 20 ms poll interval. Three runs.
The file is restored after each run.

```sh
harness/scripts/acl-latency.sh host-b 3
```

The npub must parse as a key or the ACL loader ignores it; `gen-npub.py`
produces a real secp256k1 x-only key encoded as bech32.

## Raw output

```
host=host-b runs=3 throwaway_npub=npub1a8t6nuujdvkd8fe6zpq6yhnxk8p6susfq7y8aee3482hwlauyhgqyn56gn
run 1: add_ms=756 remove_ms=984
run 2: add_ms=960 remove_ms=978
run 3: add_ms=979 remove_ms=978
restored_lines=11
```

`restored_lines=11` matches the original file (11 non-empty lines), so the
restore succeeded.

An earlier attempt produced large negative values because it mixed
`CLOCK_MONOTONIC` with epoch nanoseconds. That run was discarded; the numbers
above are from the corrected timer.

## Measurements

| Metric | Run 1 | Run 2 | Run 3 | Range |
|---|---|---|---|---|
| add (ms) | 756 | 960 | 979 | 756–979 |
| remove (ms) | 984 | 978 | 978 | 978–984 |

## Interpretation

A change is applied on the next 1-second node tick. `TICK` is
`Duration::from_secs(1)` (`src/node/mod.rs:63`) and the reloader is driven from
the tick loop (`reload_peer_acl` in `src/node/dataplane/rx_loop.rs`). The
observed values are consistent with "next tick plus a few tens of ms of load
work"; the spread is the phase of the tick when the file was written.

Consequences:

1. **Admission** of a new peer within ~1 s is fine for a link sale.
2. **Eviction** at exhaustion is not. In one tick a peer can push a large amount
   of traffic that will never be paid for. The gate needs either a much shorter
   reload period or a control-socket admission path (patch (a)), and it needs
   the pause hook (patch (b)) so it does not have to disconnect at all.
3. Any spec text that promises sub-second admission or eviction must not be
   written until (a) exists.

This is the empirical basis for P4's claim that `disconnect` is the only lever
today and that it is too blunt.

## Follow-ups

- [ ] Re-run on 0.5.3 (`host-c`/`host-a`) to check version skew.
- [ ] Re-run with a 100 ms tick build to see whether the reload cost scales.
- [ ] Cite these numbers in `spec-drafts/04-pause-and-renewal.md` (already
      cited as 756–984 ms).
- [ ] `docs/0007-current-enforcement.md` records the result.

## Artefacts

- script: `harness/scripts/acl-latency.sh`
- file restored: `/etc/fips/peers.allow`, 11 lines
- no persistent writes on `host-b`; the throwaway npub was removed
