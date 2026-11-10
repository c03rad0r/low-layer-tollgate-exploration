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
| `account.py` | npub prepaid accounts (dormant interval, exact persistent balance), not a forwarding controller |
| `nut11.py` | strict offline one-of-one P2PK condition and keyset-window checks |
| `appendlog.py` | bounded-record CRC append-only proof journal for embedded-storage design |
| `relay.py` | npub-bound app request-path payment/forward policy (not a universal mesh gate) |
| `controller.py` | `SellerController`: session state → admit/pause/resume/evict + meter; optional L0 block |
| `settlement.py` | `SettlementWorker`: redeem → journal SETTLED → exposure release |
| `vault.py` | `TokenVault`: durable bearer token, attempts, dead letter, requeue |
| `drain.py` | `SettlementDaemon`: poll the vault, settle, back off, dead-letter, `health()` |
| `frame_gate.py` | `FrameGate`: L0 nft per-MAC rate limit, blocks, optional allow-list |
| `control.py` | Unix control-socket client for the patched `set_admission` / `set_forwarding` commands |
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

185 tests: counter merge/delta/reset/direction, the four-state machine,
deadlines, notice rate limiting, idempotent ACL writes, the strict/crude pause
split, and the nullifier journal (replay, reopen, stale recovery, keyset
admission), exposure cap enforcement, the payment-gate ordering with a stub
verifier, pause/resume through a fake forwarding control, per-peer policy-drop
attribution in the meter, runtime admission over a fake control, the seller controller loop (including L0 block on eviction), and
settlement (redeem, release, reconcile a double spend) and the token
vault (crash recovery, attempts, dead letter), the drain loop (backoff,
stop conditions, health), and the frame-gate command shape/config (nft, faked
for the unit tests). Newer cases cover durable prepaid npub accounts,
dormant/rebind state, strict NUT-11 refusal rules, CRC-journal truncation,
reopen/replay, settling versus pending and compaction. `relay.py` then
integrates account, P2PK and CRC-journal proof handling behind
`PaymentGate`; tests also verify no-replay request-path credit after
cross-peer payment, link gap and process reopen.

## Not implemented

- Integration of the production account/P2PK/journal contract into one actual
  relay controller's request/forwarding path is present as a host module.
  A real FIPS request handler, transport event loop, message mux and a
  DLEQ-verifying real-mint adapter remain separate work.
- Payer-binding with the seller-encrypted preamble and msg1-ephemeral. Direct
  FIPS presenter binding is a different, smaller guarantee.
- A raw control-socket client covers only `set_forwarding` (the local patch).
  Read queries and connect/disconnect still go through `fipsctl`.
- Per-frame-class counters.
- Resale (two instances, one paying and one selling; `docs/0005`).
- Flight-board validation: real flash atomicity, power-loss recovery, key
  provisioning, RTC fallback and LR2021/Wirehair acceptance timings.

## Safety

- No mainnet funds.
- ACL writes are explicit and idempotent; the CLI prints what it would do
  without `--yes`.
- Run the sidecar on the node that owns the ACL files. The SSH runner is
  read-only by convention.
