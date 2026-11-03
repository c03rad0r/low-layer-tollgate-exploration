# 05 — Buyer role (resale)

**Question:** can a node buy transit upstream and resell it downstream without
double-charging, and what happens downstream when the upstream link is cut?

**Status:** not started. Phase 2/6. Depends on the sidecar gate and the scope
field.

## Topology

```
seller  <-- upstream link (buyer pays) --  buyer  <-- downstream link (neighbour pays) --  neighbour
```

Three nodes. The buyer is a payer on one link and a seller on another.

## What is being tested

1. **Accounting separation.** The buyer's upstream session and the neighbour's
   downstream session are different `(payer, hop, scope)` tuples. Both may
   charge `link`; neither may charge the same hop twice.
2. **No double charge for `e2e`.** If the neighbour buys `e2e`, the buyer must
   not also open a `link` charge for the same bytes.
3. **Credit bound.** Downstream unsettled credit should not exceed upstream
   prepaid remaining less a reserve.
4. **Failure propagation.** Cutting the upstream link should produce `grace`
   at the buyer and `retry_after` at the neighbour, not a silent black hole.

## Steps

1. Bring up the three nodes.
2. Seller sells `link` to the buyer. Buyer sells `link` to the neighbour.
3. Send a known byte count neighbour → seller.
4. Record the seller's counter, the buyer's upstream counter, the buyer's
   downstream counter, and the neighbour's counter.
5. Repeat with `scope=e2e` on the neighbour's session.
6. Cut the upstream link. Record downstream state transitions and timing.

## Pass criteria

- [ ] Each hop's counter matches the FMP frames on that hop.
- [ ] `link` on two hops charges twice (correct); `link` + `e2e` on the same
      flow does not (violation).
- [ ] Downstream credit never exceeds the documented bound.
- [ ] Upstream cut produces `grace`/`retry_after`, not a silent drop.

## Result file

`../../results/05-buyer-role-<date>.md`
