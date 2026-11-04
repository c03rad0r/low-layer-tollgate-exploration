# Result: FRAMEGATE — the frame-gate module drives real nftables

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** the `FrameGate` sidecar module against a real nftables
  kernel, not a mock
- **Node(s):** local T14; Alpine 3.20 container with two veth pairs and a
  bridge
- **Kernel:** host 7.0.0-42-generic; nftables 1.0.9
- **FIPS version / rev:** n/a (no `fipsd`)
- **Repo commit:** frame-gate module commit
- **Status:** pass (one demo run; the underlying per-MAC numbers are n=3 in E4)

## Question

E4 showed that one nft rule plus a dynamic set limits each source MAC
independently. The result was produced by hand-written `nft` commands in a
shell. Can the sidecar drive the same rule set through an interface, so that
session state (not an operator) owns the policy — and does the module shape
survive contact with the real tool, including JSON parsing and argument
quoting?

## Setup

```sh
harness/ethernet-lab/run-frame-gate-demo.sh
```

The container mounts `sidecar/` and the lab directory, then runs
`frame-gate-demo.py`. Topology:

```text
                        gate ingress on fgs1 (module-managed)
  fgs0 (sender) == fgs1 == fgbr == fgd0 == fgd1 (receiver, AF_PACKET)
```

The receiver sits behind the bridge, so it counts only frames that survived
the gate. Three senders use distinct source MACs:

| Sender | Offered rate | Role |
|---|---|---|
| A `02:00:00:00:00:0a` | 500 pps | under the bucket |
| B `02:00:00:00:00:0b` | 5,000 pps | over the bucket |
| C `02:00:00:00:00:0c` | 5,000 pps | over the bucket |

The module is constructed with:

```python
FrameGate(SubprocessNft(), FrameGateConfig(
    interface="fgs1", rate_pps=1000, burst=100, timeout="10m"))
```

## Scenarios and raw output

### 1. Rate limit only

```
ratelimit:
  sent  a=1,500  b=15,000  c=15,000
  recv  a=1,500  b= 3,099  c= 3,099
buckets: [02:00:00:00:00:0a, 02:00:00:00:00:0b, 02:00:00:00:00:0c]
status_has_counters: true
```

A was not dropped. B and C were each capped at ~1,000 pps.

**The bucket set contains A too.** The dynamic set creates an element for
every sender on its first frame; it does not wait for the sender to exceed the
rate. An element means "seen", not "over the limit". What proves A passed is
the receive count (1,500/1,500), not the absence of an element. This corrects
an earlier claim in the E4 write-up; see `results/E4-2026-11-03-per-mac-token-bucket.md`.

### 2. Explicit block

```
gate.block(B)
blocked:
  sent  b=15,000  c=15,000
  recv  b=     0  c= 3,099

gate.unblock(B)
unblocked:
  sent  b=15,000
  recv  b= 3,099
```

Blocking B did not affect C. Unblocking restored B's ~1,000 pps allowance
(not a full-rate pass), because the token bucket is still in force.

### 3. Allow-list mode (`default_deny=True`)

```
gate.install()          # now with the authorised set and the != rule
gate.authorise(A)
allowlist_before_b:
  recv  a=1,500  b=0

gate.authorise(B)
allowlist_after_b:
  sent  b=15,000
  recv  b= 3,098
```

Only authorised MACs pass; authorising B restores it. This mode is **off by
default** because it locks a new client out of the FMP handshake it needs in
order to pay, unless the seller provides an out-of-band checkout path.

## Rule order

`install()` writes four rules in order:

1. `ether saddr @blocked` → drop (explicit blocks win);
2. `ether saddr != @authorised` → drop (**only** when `default_deny=True`);
3. `update @bucket { ether saddr limit rate over … }` → drop;
4. `ether type 0x2121` → accept.

Order matters: a blocked MAC cannot be rescued by authorising it, and an
allow-list decision is made before spending a token.

## Validation

`FrameGateConfig.validate()` refuses an interface or table that could be
injected into the `nft` argument list, a zero rate/burst/size, an out-of-range
EtherType and a malformed timeout. MACs are normalised (dash/uppercase) and
validated before any command runs. These are unit tests, but the demo also
shows the commands are accepted by the real parser.

## Interpretation

1. **The module's command shape is correct against nftables 1.0.9.** The
   first attempts failed on a missing closing brace in the `add chain`
   invocation and on `list table` without `-j`; both were module bugs, not lab
   noise, and both are now unit-tested.
2. **Policy lives in one place.** Blocking, unblocking, authorising,
   deauthorising and bucket reset are one-line calls; the caller does not
   build nft syntax.
3. **Observation is parsed, not grepped.** `status()` returns `nft -j` JSON and
   `buckets()` handles the nested element shape the kernel actually emits.
4. **Still not authorisation.** A spoofed MAC can enter, borrow or exhaust a
   bucket, and `default_deny` is advisory. The FMP link gate keyed on the
   proven npub remains the authorisation boundary.

## Tests

130 sidecar tests pass, including 11 for the frame gate:

- install replaces the table first (idempotent) and writes the expected rules;
- `default_deny` adds the authorised set and the `!=` drop rule;
- uninstall tolerates a missing table;
- MAC normalisation and rejection before any command;
- config validation (interface, table, rate, burst, timeout, EtherType, size);
- `status()` uses `-j` and parses JSON;
- `buckets()` parses the real nested element shape.

## Caveats

- One demo run, 64-byte frames, one host, one bridge path. The per-MAC numbers
  themselves are n=3 in E4.
- The demo does not run `ndsctl` or a real AP; Exp E3 stays open.
- `default_deny` is tested on the lab bridge, not against a client that must
  first reach a checkout page.
- MAC spoofing, bucket DoS and state exhaustion are argued in
  `spec-drafts/06-frame-gate.md`, not measured here.

## Follow-ups

- [ ] Wire `FrameGate.block`/`unblock` into `SellerController` transitions so
      `evicted` (after the ACL write) also drops at L0.
- [ ] Per-MAC counters (nft element counters or a paired set).
- [ ] Real AP: combine with the `ndsctl` result (Exp E/E3).
- [ ] Provisioning-cost comparison at 1,000 MACs.

## Artefacts

- `sidecar/tollgate_fips/frame_gate.py`
- `sidecar/tests/test_frame_gate.py`
- `harness/ethernet-lab/frame-gate-demo.py`
- `harness/ethernet-lab/run-frame-gate-demo.sh`
