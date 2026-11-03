# 0001 — Three seams, and why "per transport" means scope

Status: settled by reading the FIPS design docs and source (0.6.0-dev tree,
`f4a5b4a8e6` on the fleet).

## The constraint

> "The transport layer deals exclusively in **transport addresses** … The
> mapping from transport address to FIPS identity happens at the link layer
> after the Noise IK link handshake completes."
> — `docs/design/fips-transport-layer.md`

So a TollGate placed *inside* a transport driver can only ever see
`(transport_id, remote_addr, bytes)`. In FIPS that address is not an identity:

- UDP source addresses are spoofable — the reason FIPS's msg1 rate limit is
  global rather than per-source.
- Roaming is "address follows crypto": an established session survives a NAT
  rebind, so an address-keyed gate breaks and a spoofed address can inherit a
  paid slot.
- BLE uses resolvable private addresses that rotate by default.
- Tor inbound arrives from `127.0.0.1`.
- Ethernet MACs are spoofable, and the beacon is unauthenticated.

## The three seams

| Seam | Where | Sees | Can decide | Cost |
|---|---|---|---|---|
| **L0** | transport driver, nft `netdev`, tc/XDP | transport, address, bytes | rate caps, connection caps, flood shield | cheapest |
| **L1** | FMP link admission, after msg1 DH, before msg2 / registration | npub, proven; transport; address | admit, deny, credit, per-npub rate limit | one DH (~200 µs) already spent |
| **L2** | established link data plane | npub, link, per-link counters | meter, pause transit, renew | per-frame decrypt already spent |

L1 already exists: `peers.allow` / `peers.deny` are "applied once the msg1 rate
limiter has admitted the msg1 and its DH operations have revealed the
initiator, and before the link is registered, given a session index or
answered with msg2."

## The decision

**Per-transport is a policy scope, not a code placement.** FIPS already keys
links by `(transport_id, remote_addr)`, sessions by `(transport_id,
receiver_idx)`, and exposes `transport_type` and per-link `stats` through the
control socket. A price per `(npub, transport)` is expressible today. Metering
logic inside `UdpTransport` would be duplicated seven times, could not see
npub, and would make the transport layer the place where money lives — which
is exactly what the FIPS design refuses to do.

## What is missing at each seam

- **L0** can only gate on spoofable things. Useful for floods, useless for
  authorisation.
- **L1** is binary today: admit or refuse. There is no "admitted but unpaid"
  role.
- **L2** has the counters but no policy hook. A peer either is a peer, with
  full transit rights, or is gone.

The missing piece is a **per-peer forwarding role** consulted on the data
path. Without it, "pause" is not implementable and the only lever is
`disconnect`, which also kills the payment lane. See `0004`.
