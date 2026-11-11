# Result: FIPS-APPLICATION — authenticated online payment/forwarding

- **Date:** 2026-11-11
- **Operator:** c08rad0r
- **Experiment:** host payment/account controller through a **real FIPS-local
  UDP application service set on top of two authenticated peers**.
- **Nodes:** `lt-app-a`, `lt-app-b`, `lt-app-c`, private Docker bridge.
- **FIPS:** 0.6.0-dev (`2ba790b221`) + private local forwarding image patches.
- **Unit tests:** 194 plus 14 subtests.

## Question

Once a seller has a real request handler, can it derive credit ownership from
an authenticated FIPS peer instead of a `payer_npub` field? Does the same
controller then isolate payers, reject replay and pause/renew correctly on a
live transport?

## Setup

- B runs a UDP/2122 `RelayApplicationHandler` inside its FIPS container.
- A and C each link to B as authenticated FIPS peers; each sends a PAY of
  1,000 synthetic msat and frame requests.
- `FipsIdentityResolver` maps each datagram's FIPS IPv6 to the current
  `fipsctl show peers` npub and link id. The request never gets to override
  those values.
- The P2PK `condition` is checked by the real strict offline policy. Its DLEQ
  signature isn't exercised by this harness: tests and amounts are structural,
  not mainnet or mint exchange. Earlier TWOKEY/OUTAGE tests cover real mint
  redemption.

```sh
docker compose -f harness/exp-fips-app/docker-compose.yaml down -v --remove-orphans
docker compose -f harness/exp-fips-app/docker-compose.yaml up -d --remove-orphans
PYTHONPATH=./sidecar python3 harness/exp-fips-app/run.py
```

Resetting `/tmp/opencode/fips-app-out` before a new run is required because the
bind-mounted journal intentionally survives container teardown. The runner
clears this lab-local directory in a disposable Alpine container.

## Raw outcomes

| Step | Request | FIPS-bound result |
|---|---|---|
| 1 | A PAY 1,000 | `ack`, `state=paid`, remaining=1,000 |
| 2 | C replays exactly that proof | `nack`, `code=reservation_in_flight` |
| 3 | C PAY distinct proof | `ack`, own 1,000 credit |
| 4 | A frame 100 | allowed, charge=10, remaining=990 |
| 5 | C frame 100 | allowed, charge=10, remaining=990 |
| 6 | A frame 9,900 | charge=990, transitions to `grace`, remaining=0 |
| 7 | A frame 10 | **disallowed**, charge=0, remaining=0 |
| 8 | A PAY 2,000 | `ack`, paid, remaining=2,000 (new credit on top of 0) |
| 9 | A link-down event | `ack`, dormant, remaining=2,000 |
| 10 | A next frame 100 | allowed, paid, remaining=1,990 |

Example first accepted service:

```json
{"kind": "pay", "response": {
  "t": "ack", "v": 1, "state": "paid", "remaining_msat": "1000"
}}
```

Cross-peer replay:

```json
{"kind": "pay", "response": {
  "t": "nack", "v": 1, "code": "reservation_in_flight"
}}
```

End of the sequence:

```json
{
  "t": "frame_result", "v": 1,
  "allowed": true,
  "state": "paid",
  "charged_msat": "10",
  "remaining_msat": "1990"
}
```

The response `npub` is derived from the peer table, not from a requested
identity. The `secret` in this lab is a synthetic nullifier name (`live-1`,
`live-2`); make it a **real Cashu proof secret** only in the next verifier
adapter. The experimental `locktime` P2PK tags usual Nutshell tokens would be
rejected by the strict offline policy.

## What this proves

- Allocation and settlement preparation work on a **live FIPS request path**,
  not only unit-test calls. Offline accepted proof reservation precedes credit.
- A second payer replaying a first payer's token gets no credit, even if
  their link-level FIPS identity is independently valid.
- Valid independent payers remain separately metered. Exhaustion doesn't
  allow a cheap unbilled next frame.
- Offline/dormant persistence after a link event preserves account credit; the
  next accepted transport association resumes that npub, not the selector.
- Artifacts are repeatable from fresh compose state, with no committed secrets.

## What is still not proven

- Real `cashuB` token verification with this UDP service. The DLEQ adapter
  has not yet been wired into this application loader.
- Automatic FIPS connection/peer lifecycle watchers. The dormant stage uses an
  explicit `link_down` request event to call `mark_link_down`; the next
  implementation should derive this from the daemon's connection events and
  new `link_id`.
- Any claim of arbitrary mesh forwarding gating: this app service is a local
  application request path, not a router-wide rule.
- Counting actual chargeable FMP frame classes. `frame_bytes` in this harness is
  the caller-decided application-request size. A production handler must
  construct it from the shipped FMP/socket frame and subtract policy drops.
- Production issuance/no-locktime NUT-11 tokens, on-device settlement drain,
  power-cut persistence, or LR2021 contact-window timing.

## Artifacts

- `sidecar/tollgate_fips/identity.py`
- `sidecar/tollgate_fips/envelope.py`
- `sidecar/tollgate_fips/application.py`
- `sidecar/tests/test_application.py`
- `harness/exp-fips-app/` (three configs, service, client, orchestrator).
