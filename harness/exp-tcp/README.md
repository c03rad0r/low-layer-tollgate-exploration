# Exp C over TCP

The same cut/re-admit experiment as `harness/exp-c/`, with the transport changed
from UDP to TCP. This is the first Phase 2 transport check: the gate logic, the
FMP counter boundary and the durable-eviction sequence should not depend on the
transport.

## Topology

```
seller (TCP :443, passive)  <---- TCP ---->  buyer (TCP, outbound-only)
```

Same test identities as Exp C. The seller binds `0.0.0.0:443`; the buyer has no
`bind_addr`, so it is outbound-only and dials `seller:443`. The seller has no
peer entries, so its ACL is the admission gate.

## Run

```sh
harness/exp-tcp/run-exp-tcp.sh
harness/exp-tcp/run-exp-tcp.sh --down
```

It reuses `harness/exp-c/exp_c.py` with the TCP container names and writes the
same human-readable steps plus a JSON summary with `"transport": "tcp"`.

## What to compare with UDP

| Metric | UDP (Exp C) | TCP |
|---|---|---|
| ACL effective | 0.70–0.93 s | ? |
| Bare disconnect → reconnect | 6.5–6.9 s | ? |
| Durable evict → down | 1.9–2.1 s | ? |
| Re-admit total | 2.7–2.9 s | ? |
| Link ids | 1→2→3 | ? |

The acceptance criteria are the same: the bare cut must be undone by
`auto_connect`, durable eviction must hold, and re-admission must restore a
usable link. Metering is still FMP frame bytes; TCP adds 20 + 20 bytes of
encapsulation, which the counter excludes.

## TCP-specific notes

- `2121` is not a TCP constant. This lab uses `443`, which is the upstream test
  default and a realistic firewall-traversal port. That is the motivation for
  P1 (endpoint advertisement, port removed from the protocol).
- TCP framing is header-based and reports zero overhead; the FMP frame boundary
  is still the unit the counter sees.
- Keepalive is 30 s and `TCP_NODELAY` is on by default; both can affect how
  quickly a cut is observed.
- The image exposes no host ports; both containers are on the same Docker
  bridge.

## Result

`results/01-tcp-<date>.md`
