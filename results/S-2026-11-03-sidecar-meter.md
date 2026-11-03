# Result: S — sidecar meter smoke test

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** S — does the Phase 1 sidecar read live FIPS counters and price
  them correctly?
- **Node(s):** `host-b` (remote, read-only); local daemon for `status`
- **FIPS version / rev:** 0.5.1 on the fleet; local `fipsctl` 0.5.1
- **TollGate commit:** n/a
- **Repo commit:** scaffold + harness + sidecar core (pre-commit at run time)
- **Status:** partial — meter works; no payment, demo or Exp C yet

## Question

Before building the buyer-exhausts demo, confirm that the sidecar can:

1. read the seller's own per-link counters and merge them with the peer table
   on `link_id`;
2. produce a per-npub delta over a window and price it in bytes per millisat;
3. fail loudly when asked to pause, rather than pretending.

## Setup

```sh
PYTHONPATH=sidecar python3 -m tollgate_fips.cli status
PYTHONPATH=sidecar python3 -m tollgate_fips.cli --host host-b \
  --rate 1000000 meter --seconds 5 --direction both
PYTHONPATH=sidecar python3 -m tollgate_fips.cli --rate 1000 \
  simulate --allotment-msat 1000 --top-up-msat 1000 --bytes 2000000 --grace 30
PYTHONPATH=sidecar python3 -m tollgate_fips.cli pause-check --peer npub1...
PYTHONPATH=sidecar python3 -m unittest discover -s sidecar/tests -v
```

The remote run uses `ssh -o BatchMode=yes` and only calls `fipsctl show ...`.
Nothing is written on `host-b`.

## Raw output

### Local status

```
{
  "npub": "npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh",
  "version": "0.5.1",
  "state": "running",
  "link_count": 6,
  "peer_count": 6,
  "transport_count": 2,
  "is_leaf_only": false
}
```

### Remote meter, 5 s window, 1,000,000 bytes/msat

```
window=5.0s direction=both rate=1000000 B/msat label=all_frames
npub                                                                     in        out     billable         msat
npub1ad6lxag9qmhcurz4dyyy0rgvkkr09uj6mz8ff3gzc7zwfduv89fqmwt64q        3871      13557        17428     0.017428
npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n       14789       3598        18387     0.018387
npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh       21895      27831        49726     0.049726

Boundary: FMP frame bytes at the transport API, excluding medium encapsulation; control frames included (all_frames).
```

### Session simulation

```
session=7e2e999e4edd rate=1000 B/msat allotment=1000 msat
     t  state     event
     0  unpaid    created
     0  paid      paid 1000 msat
     0  grace     charged 2000000 B = 2000.000000 msat, remaining=0.000000
     0  grace     tick
     0  paid      renewed 1000 msat
     0  grace     charged again
     0  grace     tick
    31  evicted   grace expired (grace expired)

forwarding_allowed=False payment_lane_open=False link_open=False
```

### Pause check

```
PAUSE UNSUPPORTED
FIPS has no per-peer forwarding role. The link can only be kept (and forwarding
continued) or disconnected. Use allow_disconnect=True for the crude Phase 1
fallback.
```

Exit code 1, deliberately.

### Tests

```
Ran 29 tests in 0.002s
OK
```

## Measurements

| Metric | Value |
|---|---|
| peers metered | 3 |
| window | 5.0 s |
| total billable bytes | 85,541 |
| total cost at 1,000,000 B/msat | 0.085541 msat |
| unit tests | 29 pass |

## Interpretation

The sidecar reads live counters and prices them. The three peers' byte counts
are small because `host-b` is mostly carrying control traffic at that
moment; the aggregate is labelled `all_frames` precisely because the counters do
not separate chargeable session frames from control frames.

The numbers are not a price and are not an experiment about cost. The rate is
arbitrary; the point is that the arithmetic is per-npub, per-window and
`Decimal`, and that the boundary is stated.

`pause-check` exits 1 with the missing-hook message. That is the intended
result: the sidecar does not implement `grace` by disconnecting.

## Follow-ups

- [ ] Exp C on a lab pair: exhaust, disconnect, measure re-admit, show the
      payment lane dies.
- [ ] Buyer-exhausts demo with a test mint.
- [ ] Per-class counters (FIPS patch (d)) so `all_frames` can become
      `chargeable_frames`.
- [ ] Re-run against 0.5.3 to check version skew.

## Artefacts

- `sidecar/tollgate_fips/`
- `sidecar/tests/`
- `docs/0008-gate-interface.md`
- no writes on `host-b`; read-only SSH
