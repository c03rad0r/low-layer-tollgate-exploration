# Result: PRICE — a local price penalty moves the tree parent

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** patch (c) — can a seller's price be a soft input to parent
  selection, with hysteresis?
- **Node(s):** `lt-price-r` (root), `lt-price-p1`, `lt-price-p2`, `lt-price-l`
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local patch (c)
- **TollGate commit:** n/a
- **Repo commit:** patch (c) commit
- **Status:** pass; local unmerged patch

## Question

`link_cost` is MMP-only (ETX, SRTT). Exp H showed that ACL-deny can force a
re-parent, but it costs a link and the choice is sticky. Can a price be an
input to the existing cost-aware parent selection instead, so a cheaper
candidate wins without breaking a link — and does the built-in hysteresis stop
small price changes from flapping?

## Patch

`Node.link_prices: HashMap<NodeAddr, f64>`, applied at every place the tree
builds `peer_costs`:

```text
cost = link_cost * (1 + price)      price >= 0, default 0
```

Control surface:

```text
{"command": "set_price", "params": {"npub": "npub1...", "price": 1.0}}
{"command": "set_price", "params": {"npub": "npub1...", "price": null}}   # clear
```

CLI: `fipsctl set-price <peer> <price|clear>`.

The tree already compares effective depth (`peer depth + link cost`) with
`parent_hysteresis` (default 0.2) and a `hold_down_secs` veto (default 30 s).
A price change bumps a revision counter, which forces one periodic
re-evaluation on the next tick instead of waiting `reeval_interval_secs` (60 s);
the hold-down and hysteresis still apply to the resulting discretionary switch.

## Topology

```text
        r (root)
       / \
      p1  p2
       \ /
        l   (leaf; peers p1, p2 only)
```

NodeAddr = `SHA256(x-only pubkey)[:16]`; root election is smallest-address-wins.
The root role was assigned the smallest of four test identities, so the diamond
really has `r` at depth 0 and `p1`/`p2` at depth 1. An earlier attempt failed
because the leaf held the smallest identity and became root, collapsing the
diamond into a chain — recorded here as a setup lesson, not a patch failure.

## Method

1. Bring up the diamond; wait for all four links.
2. Ping across both candidate links so both have MMP SRTT (`peer_costs` only
   includes measured peers).
3. Wait 32 s after the leaf's initial parent pick: the default hold-down is
   30 s, and a discretionary switch is suppressed inside it.
4. Small price `0.05` on the current parent; wait 5 s; expect **no switch**
   (hysteresis: `0.05` does not beat `current_eff * 0.8`).
5. Clear, then price `1.0`; poll every 100 ms for a parent change (40 s cap).
6. Ping leaf → root through the new parent.
7. Clear the price; wait 6 s; record whether the parent reverts.

```sh
harness/exp-price/run-price.sh
```

## Measurements

| Run | Baseline parent | Small price 0.05 held | Large price 1.0 moved | Switch time | Ping after | Revert after clear |
|---|---|---|---|---|---|---|
| 1 | p2 | yes | yes | 501 ms | pass | no (sticky) |
| 2 | p1 | yes | yes | 513 ms | pass | no (sticky) |
| 3 | p2 | yes | yes | 351 ms | pass | no (sticky) |

| Metric | Value (n=3) |
|---|---|
| Small price crosses hysteresis | **never** (3/3 held) |
| Large price moves the parent | **3/3** |
| Time from `set_price` to new parent | **351–513 ms** |
| Routing after the switch | pass, 0% loss |
| Revert after clearing the price | **no** (sticky, 3/3) |
| Links broken by the switch | none |

## Interpretation

1. **Price can steer parent selection without breaking a link.** A `1.0`
   penalty doubled the current parent's cost and the leaf moved to the other
   depth-1 candidate in 351–513 ms (one tick plus evaluation), with routing
   intact.
2. **The existing hysteresis is enough to stop small changes.** A `0.05`
   penalty never crossed the 0.2 margin in any run. The patch does not need its
   own damping logic.
3. **Clearing a price does not restore the old parent.** As in Exp H, choice is
   sticky: the node keeps the new parent, and the next price or failure is what
   moves it. A protocol that wants cheap-parent reversion must ask for an
   explicit re-evaluation, not just advertise a new price.
4. **The hold-down is on the critical path.** The default 30 s hold-down after a
   switch suppresses the price-driven move entirely. Any spec that promises
   fast price response has to say whether a price change is allowed to bypass
   hold-down; the local patch does not bypass it.
5. **This is a local knob, not an offer.** It uses the control socket, not a
   signed price in the offer or beacon. Wiring a real seller price into this
   map is the next step, and that is where the offer schema (P1/P2) matters.

## Caveats

- One topology, four nodes, three runs. Root order is identity-dependent.
- `price` is a unitless multiplier addend, not bytes per millisat. Mapping an
  offer price to a cost factor needs a reference rate and is not specified here.
- No payment traffic; the experiment is about parent choice.
- Local, unmerged patch. Not submitted to `jmcorgan/fips`.
- The 32 s hold-down wait dominates runtime; do not shorten it without
  accounting for the veto.

## Follow-ups

- [ ] Carry a signed price in the offer/beacon and feed `link_prices` from it.
- [ ] Define the reference rate that maps bytes-per-msat to the multiplier.
- [ ] Test whether a price change should bypass hold-down (and at what cost to
      stability).
- [ ] Repeat with a longer chain and with TCP.
- [ ] Cite this in the price-aware-routing section of the spec work.

## Artefacts

- `harness/exp-price/` (compose, four configs, orchestrator, runner)
- `0001-per-peer-forwarding.patch` (private patches repo, not published) (patches a, b and c are one file)
- `docs/0012-runtime-admission.md` (sibling patch)
