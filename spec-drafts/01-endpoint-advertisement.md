# TIP: Endpoint advertisement, and removing the port from the protocol

- **Target repo:** `OpenTollGate/tollgate`
- **Status:** Draft for PR
- **Depends on:** —
- **Experiment citations:** Exp A (`results/A-2026-11-03-counter-boundary.md`),
  Exp I (planned), fleet inventory in `docs/0007-current-enforcement.md`

## Abstract

The protocol currently treats a TCP/UDP port as part of the seller's identity.
This TIP removes the port from the protocol and replaces it with an explicit,
transport-tagged **endpoint advertisement**. `2121` remains a default for
TCP/UDP, not a protocol constant.

## Motivation

1. **Not every FIPS transport has a port.** Ethernet (EtherType `0x2121`),
   BLE (L2CAP), Tor (onion service) and Nym have no port in the TollGate sense.
   A protocol that requires one cannot describe a link sold over them.
2. **A node is not one address.** The same npub can be reachable over several
   transports at once. The fleet already runs TCP and UDP on the same node.
3. **NAT and roaming.** A fixed port in the protocol text is a promise the
   seller cannot keep behind CGNAT, and FIPS deliberately lets an established
   session survive a rebind.
4. **The port was never an identity.** The identity is the npub. The port is a
   dialling hint, and hints belong in an advertisement.

## Specification

### 1. Remove the fixed port

The following MUST be removed from normative protocol text:

- any requirement that a seller listen on port `2121`;
- any requirement that a client dial port `2121`;
- any statement that the port is part of the seller's identity or of the offer.

`2121` MAY remain as the **interface default** for TCP and UDP. It is not a
protocol constant and MUST NOT be used to identify a seller.

### 2. Add the endpoint tag

An offer or advertisement MAY carry zero or more endpoint tags:

```json
["endpoint", "<transport>", "<address>"]
```

- `<transport>` is one of `tcp`, `udp`, `ethernet`, `ble`, `tor`, `nym`,
  `socks5`, or a future FIPS transport identifier. It MUST match the
  `transport_type` the client will use.
- `<address>` is opaque to the protocol and is defined by the transport:
  - `tcp` / `udp`: `host:port`, IPv6 in brackets, e.g. `[2001:db8::1]:2121`
  - `ethernet`: a MAC address, or an interface-scoped peer identifier
  - `ble`: a BLE address or service UUID, as the transport defines
  - `tor` / `nym`: the onion or mixnet address
- An endpoint with an unknown `<transport>` MUST be ignored, not rejected.

A seller SHOULD advertise every endpoint it is willing to accept links on. A
client SHOULD try endpoints in the order given and MAY fall back to the next on
failure.

### 3. Consistency with the offer

- If an offer carries a `["transport", …]` tag (see the scope TIP), every
  `["endpoint", …]` with the same transport MUST be usable for that offer.
- An offer with `scope=link` and no endpoint for the client's transport is not
  purchasable over that transport. The client MUST NOT guess a port.
- A legacy `["port", "<n>"]` tag, if present, MUST be interpreted as
  `["endpoint", "tcp", "<host>:<n>"]` **only** when the offer also names a
  host. Otherwise it is ignored.

### 4. Security considerations

- The advertisement is not authenticated by itself. An endpoint is a **hint**.
  Authorisation is the FMP link handshake keyed on the npub. A client MUST NOT
  treat reaching an endpoint as proof of the seller's identity.
- An endpoint can be stale, NAT-translated, or malicious. Failure to connect
  MUST NOT be interpreted as refusal of payment.
- A seller MUST NOT advertise an endpoint it cannot serve; doing so is a
  denial-of-service vector against its own buyers.

## Backwards compatibility

- Existing sellers that listen on `2121` continue to work: the client's
  interface default supplies the port when no endpoint is advertised.
- Existing clients that hard-code `2121` continue to work against sellers that
  use the default. They will not work against sellers on other ports, which is
  already true today.
- No wire-format change to FMP. This is an offer/advertisement change only.

## Reference implementation notes

- A sidecar can synthesise endpoints from `fipsctl show transports` and the
  node's own configuration; it does not need a FIPS change.
- The Ethernet demo (`experiments/03-ethernet/`) advertises an EtherType/MAC
  endpoint, which is the case that motivates the TIP.

## Citation

- Counter boundary and transport inventory: `docs/0007-current-enforcement.md`,
  `results/A-2026-11-03-counter-boundary.md`.
- Multi-transport reconciliation: Exp I (planned).
