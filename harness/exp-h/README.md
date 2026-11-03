# Exp H — can ACL-deny force re-parenting?

**Question:** if a node's current tree parent refuses it, does the node
re-parent to its alternate peer, how long does convergence take, and how much
churn is there?

**Status:** harness built, not yet run.

## Topology

Three nodes in a triangle, each directly peered with the other two:

```
        p (passive)
       / \
      /   \
     x --- q
```

`p` has no peer entries and never dials; `x` and `q` auto-connect to `p` and to
each other. All three run strict ACLs (`ALL` in `peers.deny`, the other two in
`peers.allow`).

## Method

1. Bring up the triangle and wait until every node has two direct peers.
2. Read the tree: each node's parent, children, depth and root flag.
3. Pick the deepest non-root node (`child`) that has a parent and an alternate
   peer.
4. Deny `child` on `parent`'s ACL, wait for the deny to be effective, then
   `fipsctl disconnect` the child.
5. Watch the child's `is_parent` peer until it changes to the alternate, or the
   child becomes root.
6. Record: ACL latency, disconnect latency, time to re-parent, parent
   transitions, depth/root changes, and whether the child can still ping the
   old parent through the new path.
7. Re-admit the child on the parent and record whether the link returns and
   whether the tree reverts.

The measurement is not "does the packet survive" — that is routing. It is
whether **ACL denial of a parent is a usable lever for changing the tree**, and
what it costs.

## Run

```sh
harness/exp-h/run-exp-h.sh
harness/exp-h/run-exp-h.sh --down
```

Requires `fips-test:latest` from the pinned FIPS tree (`2ba790b`).

## What would falsify the design

- The child stays parentless and the mesh splits, even though the alternate peer
  is reachable. Then ACL-deny is not a safe re-parenting lever.
- The child re-parents but routing does not recover (ping fails through the new
  path). Then the tree changed but the link sale did not.
- Re-parenting takes so long that the payment lane dies first. That is a number
  for P4 and patch (c).

## Result

`results/H-<date>.md`
