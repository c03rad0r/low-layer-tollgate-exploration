# 0017 — The frame-gate module

Status: implemented in `sidecar/tollgate_fips/frame_gate.py`; 11 tests and a
real-nftables demo (`results/FRAMEGATE-2026-11-03-module.md`). Background:
`docs/0006-frame-gate.md`, E2/E4 results, `spec-drafts/06-frame-gate.md`.

## What it is

A thin control surface over the nftables rule set that rate-limits and blocks
FIPS frames **before FMP is parsed**:

```python
from tollgate_fips import FrameGate, FrameGateConfig

gate = FrameGate(config=FrameGateConfig(
    interface="eth0", rate_pps=1000, burst=100, timeout="10m"))
gate.install()
gate.block("02:00:00:00:00:0b")
gate.unblock("02:00:00:00:00:0b")
gate.status()    # parsed `nft -j list table` JSON
gate.buckets()   # MACs with bucket state
```

It complements `FipsGate`, which works at L1/L2 on the proven npub. This module
is L0: MAC and EtherType only. It is **rate/abuse control, not authorisation**
(see `spec-drafts/06-frame-gate.md`).

## Rule order

`install()` replaces the table (idempotent, clears stale state) and writes:

1. `ether type 0x2121 ether saddr @blocked` → drop;
2. `ether type 0x2121 ether saddr != @authorised` → drop, **only** when
   `default_deny=True`;
3. `ether type 0x2121 update @bucket { ether saddr limit rate over N/second
   burst M packets }` → drop;
4. `ether type 0x2121` → accept.

Explicit blocks win over the allow-list, so authorising a blocked MAC does not
rescue it. The allow-list decision happens before a token is spent.

## Policy

| Call | Effect |
|---|---|
| `install()` / `uninstall()` | create or delete the table, sets, chain and rules |
| `block(mac)` / `unblock(mac)` | drop every `0x2121` frame from a MAC (any mode) |
| `authorise(mac)` / `deauthorise(mac)` | manage the allow-list (`default_deny` only) |
| `reset_bucket(mac)` | forget a MAC's token state; next frame gets a full burst |
| `status()` | parsed nft JSON (rules, counters, set elements) |
| `buckets()` | MACs that currently have a bucket element |

`uninstall`, `unblock` and `deauthorise` pass `check=False`, so removing an
absent table or element is not an error.

## `default_deny` is dangerous

A gate that drops unknown MACs can lock a new client out of the FMP handshake
it needs in order to reach checkout. `default_deny` is therefore off by
default and is only safe when the seller provides an out-of-band payment path
(captive portal, HTTPS, QR, invoice). The spec draft requires one of those.

The same rule applies to FIPS session states: an `unpaid` or `grace` session is
paused at L1/L2, not dropped at L0. The L0 block is for devices that are not
peers, or for `evicted` sessions after the durable eviction completed.

## The bucket is per MAC, but the set is not a list of abusers

`update @bucket { ether saddr limit rate over … }` creates an element for every
sender on its first frame, whether or not it is over the rate. The element
holds that sender's token state; the `limit` decides the drop.

Consequences:

- `buckets()` returning a MAC means "this sender has been seen", **not** "this
  sender is over the limit". Use receive/drop counters for the latter.
- `timeout` (default `10m`) expires idle elements. Without it the set grows
  with every sender ever seen.
- `max_entries` (default 65535) is a hard cap and a memory bound.
- `reset_bucket(mac)` is the cheap way to clear state after a policy change or
  a false positive.

## Validation

`FrameGateConfig.validate()` checks the interface and table against a strict
character set (they become `nft` argv, not a shell string), requires a positive
rate/burst/size and a well-formed EtherType and timeout. MACs are normalised
from `aa-bb-…`/uppercase and validated before any subprocess call. This keeps a
caller-supplied value from becoming extra nft syntax.

## What it does not do

- **Authorise.** A MAC is spoofable; this never credits a session or admits a
  peer to the mesh.
- **Charge.** Dropped frames are not billable; the meter must subtract the
  gate's drop delta for the same window (`docs/0002`).
- **Gate non-Ethernet transports.** UDP, TCP, Tor and BLE have no pre-FMP
  frame to key on; they rely on the FMP link gate alone.
- **Manage sessions.** It exposes the levers; `SellerController` decides when
  to pull them. Wiring `evicted → block` is a follow-up.
- **Expose per-MAC drop counters.** nft's `counter` is global to the rule.
  Per-MAC accounting needs element counters or a different design.

## Tests

`sidecar/tests/test_frame_gate.py` (11 tests) covers install/uninstall/replace,
the `default_deny` rule set, command shape, ordering, MAC normalisation and
rejection, config validation, and JSON parsing of the real element shape. The
demo (`harness/ethernet-lab/run-frame-gate-demo.sh`) runs the same module
against nftables 1.0.9 with three concurrent senders and a block/unblock and
allow-list scenario.
