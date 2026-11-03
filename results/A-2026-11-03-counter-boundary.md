# Result: A — counter boundary

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** A — do FIPS counters count FMP frame bytes or payload bytes?
- **Node(s):** `host-a` (fleet sample); source tree `0.6.0-dev`
- **FIPS version / rev:** 0.5.3 (`f4a5b4a8e6`) on the fleet; local clone of
  `jmcorgan/fips` for source citations
- **TollGate commit:** n/a
- **Repo commit:** scaffold (pre-first-commit)
- **Status:** pass (source inspection decisive; packet-capture confirmation not
  run)

## Question

If a `scope=link` session meters bytes, which bytes? The FMP frame as it crosses
the socket, or only the payload inside it? The answer decides the metering TIP
and whether a sidecar can use the daemon's own counters.

## Setup

Two independent methods:

1. **Source inspection** of the FIPS tree: find every `record_sent` /
   `record_recv` call and determine what length is passed.
2. **Fleet sample**: sample `fipsctl show transports` and `fipsctl show links`
   twice, five seconds apart, on `host-a`, which carries production-ish traffic.

```sh
harness/scripts/sample-counters.sh host-a 5 c03rad0r@gateway.example
```

The planned third method — packet capture on a lab node, comparing `show links`
deltas to `nft` counters for the same interval — was **not run** because there
is no Ethernet-transport lab node yet. It would confirm, not decide; the source
is unambiguous.

## Raw output

### Fleet sample, `host-a`

```
host=host-a window=5.0s

transports (delta, rate, mean frame size):
  id=2 type=tcp      bytes=           0 pkts=       0 rate=     0.0 kB/s mean_frame=   0.0 B
  id=1 type=udp      bytes=     1404190 pkts=    1930 rate=   280.8 kB/s mean_frame= 727.6 B

links (delta bytes, from per-peer stats):
  link=2 tid=1 addr=192.168.2.4:2121 bytes=1363670
  link=318 tid=1 addr=192.168.2.121:2121 bytes=3717
  link=323 tid=1 addr=203.0.113.108:2121 bytes=0

sum(link delta)=1367387
```

An earlier sample of the same node gave `bytes_recv` ≈ 1.62 GB over 2.49 M
packets ≈ **653 B/pkt**. Both samples are consistent with full FMP frames, not
payload-only counts.

### Source citations

| Path | Line | Code |
|---|---|---|
| `src/transport/udp/mod.rs` | 644, 707 | `stats.record_recv(len);` where `len` is the `recvmsg` return |
| `src/transport/udp/stats.rs` | 29, 61, 97 | `bytes_recv` is `AtomicU64`; `record_recv` adds `bytes` |
| `src/node/mod.rs` | 4592, 4664 | `peer.link_stats_mut().record_sent(bytes_sent);` with `bytes_sent` = sealed `wire_packet` length |
| `core/src/transport/types.rs` | 282–310 | `bytes_sent` / `bytes_recv` counters and their `record_*` methods |
| `src/transport/ethernet/mod.rs` | 1275 | `stats.record_recv(len);` **before** the 3-byte FIPS frame header is stripped |
| `src/transport/tcp/mod.rs` | 1532 | `stats.record_recv(data.len());` |

The FMP frame layout gives the arithmetic:

```
4  common prefix
12 remaining header (receiver idx, counter, type/timestamp)
+  payload
16 AEAD tag
```

## Measurements

| Metric | Value | Notes |
|---|---|---|
| transport bytes (5 s) | 1,404,190 | UDP only; TCP idle |
| transport packets (5 s) | 1,930 | |
| mean frame | 727.6 B | includes all frames on the transport |
| sum of per-link deltas | 1,367,387 | three links |
| unattributed difference | 36,803 B (2.6 %) | handshake/control frames not in any link's counter |
| earlier mean frame | ≈ 653 B | different window, same node |

## Interpretation

FIPS counters are **FMP frame bytes at the transport API**: the datagram handed
to or returned from the socket. They include the common prefix, the remaining
header and the AEAD tag, and they exclude medium encapsulation (UDP 8 + IPv6
40, TCP 20 + 20, Ethernet 14, BLE L2CAP).

Two consequences:

1. A link session can use the daemon's counters directly. It does not need to
   re-count at a different boundary.
2. The per-link counter is **not** the transport counter. In this sample 2.6 %
   of transport bytes were not attributed to any link — handshake and
   transport-level frames. A gate that bills from `show transports` charges for
   those; a gate that bills from `show links` does not. The spec must say which
   one, and the honest answer for `scope=link` is the per-link counter, with the
   unattributed share treated as the seller's cost.

The sample cannot by itself distinguish frame from payload, but the source
does, and the arithmetic matches: mean frame 727.6 B with a 32-byte fixed
overhead is a payload mean of ~696 B, both plausible. The decisive evidence is
the call sites.

## Follow-ups

- [ ] Packet-capture confirmation on the lab Ethernet pair (Phase 2).
- [ ] `docs/0002-metering-boundary.md` already states the rule; add the
      per-link vs transport distinction above.
- [ ] `spec-drafts/03-wire-byte-metering.md` names the per-link counter.
- [ ] Per-class counters remain missing; P3 states the limitation.

## Artefacts

- script: `harness/scripts/sample-counters.sh`
- no files written on `host-a`; read-only
- disk free not required (no writes)
