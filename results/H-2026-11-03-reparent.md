# Result: H — ACL-deny forces re-parenting

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** H — can an ACL deny of the current parent force re-parenting?
- **Node(s):** `lt-exp-h-p`, `lt-exp-h-x`, `lt-exp-h-q` (three-node triangle)
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`)
- **TollGate commit:** n/a
- **Repo commit:** Exp H harness commit
- **Status:** pass

## Question

Price-aware parent selection does not exist: `link_cost` is MMP-only. The crude
workaround is to deny the current parent and let the tree re-form. Does that
work, how long does it take, and what churn does it cause?

## Setup

Three nodes in a triangle, each directly peered with the other two:

```
        p (passive)
       / \
      /   \
     x --- q
```

`p` has no peer entries and never dials. `x` and `q` auto-connect to `p` and to
each other. All three run strict ACLs (`ALL` in `peers.deny`, the other two in
`peers.allow`). Test identities derive from `low-layer-tollgate-exp-h`; they are
not secrets.

The orchestrator picks the deepest non-root node with a parent and an alternate
peer, denies it on its parent, waits for the ACL, disconnects, and watches the
child's `is_parent` peer.

```sh
harness/exp-h/run-exp-h.sh
```

## Raw output

```
nodes: {
  "p": "npub1yfe7j2r8nfyqfghcqq2n2zpmwn3de60hv05uwg6jgw82w5ht56csc07la3",
  "x": "npub1kec6dmrn2fh5ef44j8784lnyadx6gqnkadn9fz5fu7pyqphc00qq46hjg8",
  "q": "npub1scf2vfjxmh23atczhfxe48zc7fglcxfep3jl28j64fq2nl9g4c9qt9qjhc"
}
ACL effective ms: {'p': 572, 'x': 885, 'q': 154}
triangle formed in 158 ms: {'p': 2, 'x': 2, 'q': 2}
topology before: {
  "p": {"parent_name": "x", "children": ["q"], "depth": 1.0, "is_root": false, "peers": 2},
  "x": {"parent_name": null, "children": ["p"], "depth": 0, "is_root": true, "peers": 2},
  "q": {"parent_name": "p", "children": [], "depth": 2.01, "is_root": false, "peers": 2}
}
chosen child=q depth=2.01 parent=p alternate=x
ping q->p before: ok=True loss=0.0%
deny q on p: ACL effective in 163 ms; allow=['x']
disconnect q on p: 51 ms
re-parent: success_to_x=True became_root=False final_parent=x at 109 ms
transitions: [{'at_ms': 109, 'from': 'p', 'to': 'x'}]
topology after: {
  "p": {"parent_name": "x", "children": [], "depth": 1.01, "is_root": false, "peers": 1},
  "x": {"parent_name": null, "children": ["p", "q"], "depth": 0, "is_root": true, "peers": 2},
  "q": {"parent_name": "x", "children": [], "depth": 1.01, "is_root": false, "peers": 1}
}
ping q->p after: ok=True loss=0.0%
ping x->p: ok=True loss=0.0%
re-admit: mode=auto total=1619 ms (acl 454 + link 1165)
topology after re-admit: {
  "p": {"parent_name": "x", "children": [], "depth": 1.01, "is_root": false, "peers": 2},
  "x": {"parent_name": null, "children": ["p", "q"], "depth": 0, "is_root": true, "peers": 2},
  "q": {"parent_name": "x", "children": [], "depth": 1.01, "is_root": false, "peers": 2}
}
ping after re-admit: ok=True loss=0.0%
```

## Measurements

| Metric | Value |
|---|---|
| Triangle formed | 158 ms |
| ACL effective: p / x / q | 572 / 885 / 154 ms |
| Chosen child / parent / alternate | `q` / `p` / `x` |
| Child depth before | 2.01 |
| ACL deny effective on parent | 163 ms |
| Disconnect command | 51 ms |
| **Time to re-parent** | **109 ms** |
| Parent transitions | 1 (`p` → `x`) |
| Child became root | no |
| Ping child→old parent before | pass |
| Ping child→old parent after | **pass** (via `x`) |
| Links before / after | 3 / 2 (p–q dropped) |
| Re-admit ACL | 454 ms |
| Re-admit link | 1,165 ms |
| Re-admit total | **1,619 ms** |
| Topology after re-admit | unchanged (`q` stays child of `x`) |
| Ping after re-admit | pass |

## Interpretation

1. **ACL-deny of the current parent is a usable re-parenting lever.** The child
   moved from `p` to `x` in 109 ms, one transition, and routing recovered. The
   old parent stayed reachable through the new path (ping passed).
2. **The tree did not split.** The alternate peer was a viable parent, so the
   child did not become a second root. This is the good case; a chain with no
   alternate would be the falsification test.
3. **The cost is one link.** The `p`–`q` link was dropped, taking both endpoints
   to one peer; the tree became a star at `x`. Re-admitting `q` on `p` restored
   the link but did **not** revert the parent. Parent choice is sticky.
4. **Stickiness matters for price-aware routing.** If a cheaper parent appears,
   restoring the link is not enough; the child keeps the old parent. Patch (c)
   needs an explicit re-evaluation with hysteresis, not just an ACL change.
5. **ACL latency dominates the lever.** The deny itself was 163 ms in this run
   (tick phase), but the p/x/q writes ranged 154–885 ms. Re-admission cost
   1.6 s. A price-aware parent change is therefore a sub-second-to-few-second
   operation, not a per-packet decision.

## Caveats

- One run, one triangle, one tree shape (`x` root, `p` child, `q` grandchild).
  Repeat with different root orders and with a chain that has no alternate.
- No payment. "Re-admit" is an ACL allow plus a handshake; it does not require a
  new token.
- ICMP only. The routing recovery is end-to-end reachability, not a throughput
  measurement.
- The parent-choice stickiness is observed, not explained; it may be a property
  of the tree protocol's hysteresis rather than a configurable policy.

## Follow-ups

- [ ] Repeat 3–5 times with different root orders.
- [ ] Run the negative case: a chain with no alternate peer; expect a split.
- [ ] Measure whether a price change can trigger the same re-parent without an
      ACL deny (patch (c)).
- [ ] Repeat over TCP and Ethernet.
- [ ] Add the numbers to the patch (c) write-up.

## Artefacts

- `harness/exp-h/docker-compose.yaml`
- `harness/exp-h/configs/`
- `harness/exp-h/exp_h.py`
- `harness/exp-h/run-exp-h.sh`
- containers left up for inspection at run time
