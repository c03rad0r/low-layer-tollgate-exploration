# 04 — BLE

**Question:** does the gate work over BLE, and is `mark_verified` the right
payer hook?

**Status:** not started. Phase 2. Requires BLE hardware; no fleet node has it
(see `Q3` in `CHECKLIST.md`).

## Topology

```
seller (fipsd, ble)  <~~ BLE ~~>  buyer (fipsd, ble)
```

Two machines with working BLE controllers, or one machine and a second
adapter. A virtual HCI is not enough to test real air time.

## Why BLE is different

- **Resolvable private addresses rotate by default.** A gate keyed on the BLE
  address breaks every rotation. The npub is the identity; the address is not.
- **A BLE frame is mostly overhead.** A ~21-byte frame carrying a 5-byte inner
  header is ~76 % overhead. This is the strongest argument for charging wire
  bytes rather than payload bytes.
- **Air time is the cost.** The seller's radio is occupied while it carries
  the buyer's traffic, and that cost is symmetric in a way a WAN uplink is not.
- **Pairing/association is not authorisation.** Being connected at the BLE
  level says nothing about payment.

## Steps

1. Bring up both nodes with the BLE transport.
2. Establish the link. Confirm the peer address rotates and the npub does not.
3. Run the shared acceptance test.
4. Record frame sizes and the wire-byte count. Compare to the payload count and
   state the overhead ratio.
5. Check `mark_verified`: does it fire at the right point to be a payer hook,
   i.e. after the identity is known and before traffic is forwarded?
6. Record time-to-admit and the effect of a rotation mid-session.

## Pass criteria

- [ ] Session reaches all four states with a rotating peer address.
- [ ] Wire-byte counter is stable across address rotation.
- [ ] `mark_verified` is documented as a hook or rejected with a reason.
- [ ] Overhead ratio is recorded and cited in P3.

## Blocker

If no BLE hardware is available, this experiment stays blocked. Do not
substitute a virtual controller and call it a BLE result; the air-time and
rotation behaviour is the point.
