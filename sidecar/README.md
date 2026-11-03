# `tollgate-fips` — Phase 1 sidecar

A small gate over the FIPS control socket. It admits peers through the ACL
files, meters the seller's own per-link counters, and evicts with
`fipsctl disconnect`. It does **not** pretend FIPS can pause one peer's
forwarding.

Status: Phase 1 core. Meter, session machine and ACL writes are unit-tested and
the meter has been run against `host-b`. The buyer-exhausts demo and Exp C
are not done.

## Run

From the repo root:

```sh
PYTHONPATH=sidecar python3 -m tollgate_fips.cli status
PYTHONPATH=sidecar python3 -m tollgate_fips.cli --rate 1000000 meter --seconds 5
PYTHONPATH=sidecar python3 -m tollgate_fips.cli simulate --allotment-msat 1000 --bytes 2000000
PYTHONPATH=sidecar python3 -m tollgate_fips.cli pause-check --peer npub1...
```

Inspect a remote node read-only (uses `ssh -o BatchMode=yes`):

```sh
PYTHONPATH=sidecar python3 -m tollgate_fips.cli --host host-b meter --seconds 5
```

ACL writes are dry-run unless `--yes`:

```sh
PYTHONPATH=sidecar python3 -m tollgate_fips.cli --yes admit npub1...
PYTHONPATH=sidecar python3 -m tollgate_fips.cli --yes deny npub1...
```

`admit` removes a matching deny entry and `deny` removes a matching allow
entry, so the two files cannot contradict each other for the same npub.

## What is implemented

| Module | What |
|---|---|
| `runner.py` | local or SSH command runner |
| `fipsctl.py` | typed `show status/links/peers/transports`, `disconnect` |
| `meter.py` | merge peers+links on `link_id`, per-link delta, reset rule, bytes/msat |
| `session.py` | `unpaid → paid → grace → evicted`, deadlines, notices |
| `gate.py` | `admit / deny / meter / pause / resume / evict`, `FileAclStore` |
| `journal.py` | durable nullifier journal (`RESERVED → SETTLED | SPENT`), keyset admission predicate |
| `exposure.py` | per-payer/mint/unit exposure cap, reserved before the journal row |
| `payment.py` | `PaymentGate`: verifier → exposure → journal, receipt/settle/reject |
| `control.py` | Unix control-socket client for the patched `set_forwarding` command |
| `cli.py` | `status`, `meter`, `simulate`, `pause-check`, `admit`, `deny` |

The gate contract is in `docs/0008-gate-interface.md`.

## Metering

- Boundary: FMP frame bytes at the transport API. Excludes UDP/IP/TCP/Ethernet
  encapsulation. Includes control frames; readings are labelled `all_frames`
  until a per-class counter exists.
- Source: `show peers` for npub + counters, `show links` for `transport_id`,
  `remote_addr`, `transport_type`, merged on `link_id`.
- Reset: if a link's counter goes backwards, the new value is the delta for the
  new epoch. No refund, no carry-forward.
- Price: **bytes per millisat**. `cost_msat = billable_bytes / rate`. `Decimal`,
  not float.
- Direction: `both` (default), `in`, `out`.

## Pause

Upstream FIPS 0.5.x and 0.6.x have no per-peer forwarding role. If a
`UnixControl` is supplied, `pause()` sends the local patch's `set_forwarding`
command and returns `mode="transit-blocked"`: the link, Noise session and local
delivery stay. `resume()` clears it. On unpatched FIPS the command is unknown,
so strict mode raises `PAUSE UNSUPPORTED`; `--allow-disconnect` degrades to a
durable eviction and says the payment lane died.

## Tests

```sh
PYTHONPATH=sidecar python3 -m unittest discover -s sidecar/tests -v
```

74 tests: counter merge/delta/reset/direction, the four-state machine,
deadlines, notice rate limiting, idempotent ACL writes, the strict/crude pause
split, and the nullifier journal (replay, reopen, stale recovery, keyset
admission), exposure cap enforcement, the payment-gate ordering with a stub
verifier, pause/resume through a fake forwarding control, and per-peer
policy-drop attribution in the meter.

## Not implemented

- Payment verification and mint interaction (Phase 3). The spent journal core
  is implemented; it is not yet fed by a verifier.
- A raw control-socket client covers only `set_forwarding` (the local patch).
  Read queries and connect/disconnect still go through `fipsctl`.
- Per-frame-class counters.
- The buyer-exhausts demo and Exp C. Those need a lab pair and a test mint.
- Resale (two instances, one paying and one selling; `docs/0005`).

## Safety

- No mainnet funds.
- ACL writes are explicit and idempotent; the CLI prints what it would do
  without `--yes`.
- Run the sidecar on the node that owns the ACL files. The SSH runner is
  read-only by convention.
