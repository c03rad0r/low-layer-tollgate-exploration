# 0023 — Live FIPS application-relay integration

The integration milestone for a **real FIPS-local UDP application**, following
`docs/0021-npub-prepaid-accounts.md` and `docs/0022-app-relay-integration.md`.

## Delivered

- [x] `FipsIdentityResolver`: datagram IPv6 → current authenticated npub + link id.
- [x] `RelayApplicationHandler`: `PAY`, frame requests, `link_down`, `tick` and an offer request.
- [x] Internal v1 envelope: `pay`, `frame`, `link_down`, `tick`, `offer_request` plus ack/nack/result structures.
- [x] Request IDs are correlation, not replay identity or transaction safety.
- [x] Per-request strict P2PK/lock checks; layered exposure and proof reservation before credit.
- [x] Unknown source/unknown npeer errors; no claimed payer identity is authoritative.
- [x] Two actual authenticated FIPS clients with distinct accounts on one service.
- [x] Cross-peer PAY replay → `reservation_in_flight`.
- [x] Same budget exhaustion → `grace` → following request blocked at zero.
- [x] Valid renewal resumes at 2,000 msat; after explicit down event next frame accepts at 1,990.
- [x] 194 passing tests + 14 subtests (suite includes all previous primitives).

## Artifact map

| Layer | File |
|---|---|
| Identity lookup | `sidecar/tollgate_fips/identity.py` |
| Request/schema handling | `sidecar/tollgate_fips/envelope.py` |
| Application logic | `sidecar/tollgate_fips/application.py` |
| Payment/accounting | `relay.py` / `account.py` / `payment.py` |
| Nullifier record adapter | `appendlog.py` (`CrcNullifierJournal`) |
| 3-node live lab | `harness/exp-fips-app/` |
| Measurement | `results/FIPS-APPLICATION-2026-11-11-account-payment-binding.md` |

## Still required before a production integration

- [ ] Replace the verifier used in the app loader with an actual `cashuB` DLEQ
      + P2PK verifier backed by the seller-cached allowed keysets.
- [ ] Give the offer the actual compressed P2PK lock key and explicit mint/settlement policy;
      use real-mint vectors, including valid no-reclaim NUT-11 issuance.
- [ ] Watch FIPS peer/lifecycle updates to drive `link_down`/rebind automatically.
      This lab sends an explicit `link_down` event; it does not yet implement a
      peer watcher.
- [ ] Implement the actual data/service frame path rather than passing declared
      frame bytes through a test request. Use declared FMP boundary counters;
      subtract any policy drops and do not bill them.
- [ ] Send normal `nack` error codes for bad encodings, replay, nongenuine proof,
      exhausted balance, keyset failure, between-links current npub change and cap exhaustion.
- [ ] Persist accounts/log on embedded storage under real compact,
      recover and settlement-examples; work out safe claim before redemptions.
- [ ] Complete CRC-vault settlement with batching, operator-visible failures
      and no false exposure release from dead letters.
- [ ] FIPS integration with the balloon-fresh service mux: correlate requests to
      one buyer account and service only while policy permits.

## Release gates deliberately open

- [ ] Verify this end-to-end path against radio hardware only after the host and
      FIPS regression suites are green. Do not treat lab success as a flight proof.
- [ ] Real LoRa packet/pass-window timing.
- [ ] MCU memory, flash atomicity, wear and power-cut recovery.
- [ ] Default-caps for multiple accounts and rate/flood limits under first-contact abuse.
- [ ] Key rotation/revocation, flight provisioning, signed release and rollback.
- [ ] Operator metrics and runbook for unsettled notes, expired keysets and dead letters.

This is actual transport integration on Docker peers, not a radio flight demo.
