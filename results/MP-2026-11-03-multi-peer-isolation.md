# Result: MP — per-peer block is isolated on a multi-peer seller

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** multi-peer version of PB — does blocking one client's transit
  leave another client untouched, and are drops attributed per peer?
- **Node(s):** `lt-mp-a`, `lt-mp-b`, `lt-mp-c`, `lt-mp-d` (star, B is root and
  transit)
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local unmerged patch (b)
- **TollGate commit:** n/a
- **Repo commit:** multi-peer commit
- **Status:** pass, n=3

## Question

PB blocked one peer on a three-node chain. With a single client, a node-wide
drop would look identical to a per-peer one: there was only one peer to drop.
The spec claim is narrower — blocking A must not affect C. That needs at least
two clients that both transit the same seller.

## Setup

```text
        A  edc60ce1…  \
                      \
        C  af212068…  ---  B  1e45446b…  (root, transit, seller)
                      /
        D  cea16d4f… /
```

All three clients dial B over UDP. B is the root (smallest NodeAddr), so A, C
and D are its children. A→D and C→D both transit B; A→B and C→B are local at B.

```sh
harness/exp-multipeer/run-multipeer.sh
```

The patched B exposes `set_forwarding` on its control socket. The orchestrator
waits for every link, probes D from A and C to populate the routes, checks the
baseline, then runs three block/allow cycles:

- `block A`: A→D must fail, C→D must keep working, A→B local must stay up, the
  A–B link must survive, and B's `policy_blocked_by_peer` must grow under A
  only;
- `allow A`: A→D must resume.

## Raw output

```text
addrs: a=edc60ce11628233dce5a346e174da5e3
       b=1e45446be7d450194ab1e8eff75c1b76
       c=af2120681bb7114fd23b615d4a36a7d5
       d=cea16d4f91c58ca297905ed377d4e812
link a-b up in 146 ms
link c-b up in 144 ms
link d-b up in 141 ms

baseline: a->d=True c->d=True a->b=True c->b=True

topology:
  a: parent=b peers=1
  b: root      peers=3
  c: parent=b peers=1
  d: parent=b peers=1
```

Each cycle, while A is blocked:

| Cycle | A→D | A→D loss | C→D | C→D loss | A→B | C→B | A–B link | Drops filed under A | Under C |
|---|---|---|---|---|---|---|---|---|---|
| 1 | fail | 100.0 % | ok | 0.0 % | ok | ok | up | 24 pkt / 3,139 B | none |
| 2 | fail | 100.0 % | ok | 0.0 % | ok | ok | up | 50 / 6,392 (Δ 26 / 3,253) | none |
| 3 | fail | 100.0 % | ok | 0.0 % | ok | ok | up | 74 / 9,395 (Δ 24 / 3,003) | none |

After `allow A`, A→D and C→D are both `ok` in all three cycles.

The attribution rows are cumulative (the patch does not reset counters on
allow), so the cycle deltas are the useful number: roughly 24 packets and
3,000 bytes per blocked phase, all under A. C never appears in
`policy_blocked_by_peer`.

## Interpretation

1. **The block is per peer, not node-wide.** C→D and C→B were unaffected in
   every cycle while A→D was 100 % dropped. A node-wide forwarding toggle would
   have failed this.
2. **The link and local path survive.** A→B still worked and the A–B peer row
   stayed connected. This is the same property PB showed, now with a second
   client proving the seller did not lose its own connectivity.
3. **Attribution is per peer.** Every dropped packet was filed under A's
   node address; there was no C row. A node-wide counter would have shown the
   bytes but not who caused them, which is exactly what per-peer policy needs
   for billing-free pause.
4. **Allow restores service without a reconnect.** A→D resumed on the existing
   link after `allow`, consistent with PB and PD.
5. **Four nodes are enough to distinguish the two policies.** The earlier
   single-client result could not; this one can.

## Method note: the config identity is a hex secp256k1 seed

The first four-node attempt used a bech32 `nsec` string in `node.identity.nsec`.
FIPS expects the **hex** seed (as every other lab config does). It derived a
different identity from that string, which still connected (inbound peers are
not gated by the local peer list) but made the planned star topology false
(the unintended node became root). The orchestrator now asserts that B is root
before running, and the D identity was regenerated from a hex seed whose
NodeAddr is larger than B's.

This is a useful trap for anyone copying identities between tools: an npub is
not the bech32 encoding of the same bytes FIPS hashes unless the curve is
secp256k1 and the seed is hex.

## Caveats

- One host, four containers, one bridge, UDP only. No lossy radio, no churn.
- ICMP probes, not FIPS application payload; 24 packets per phase reflects the
  probe/retry pattern, not a throughput measurement.
- The counters are cumulative and were not reset between cycles; deltas are
  computed from consecutive snapshots.
- B is root in this run because its NodeAddr is the smallest. The isolation
  property should hold for any parent, but only this tree was measured.
- No payment is involved; PD already covers pause with a real payment.

## Follow-ups

- [ ] Repeat with payment traffic on the unaffected client (revenue isolation,
      not just reachability).
- [ ] Repeat over Ethernet/TCP.
- [ ] Reset `policy_blocked_by_peer` counters on allow, or expose a windowed
      counter, so operator views do not need deltas.

## Artefacts

- `harness/exp-multipeer/docker-compose.yaml`
- `harness/exp-multipeer/configs/{a,b,c,d}.yaml`
- `harness/exp-multipeer/multipeer.py`
- `harness/exp-multipeer/run-multipeer.sh`
- `harness/pause/control.py` (shared control client)
