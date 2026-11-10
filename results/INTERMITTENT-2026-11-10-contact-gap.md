# Result: INTERMITTENT — a deadline, not link loss, evicts the session

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-INTERMITTENT (docs/0019, decisions D3/D4)
- **Nodes:** `lt-int-seller`, `lt-int-buyer`, private Docker bridge
- **FIPS:** 0.6.0-dev (rev `2ba790b221`)
- **Status:** completed one 90-second gap per session model

## Question

Does a buyer disappear and reappear with credit intact, or does the balloon's
session clock turn a normal contact gap into an eviction?

## Setup

The same buyer container is stopped for 90 seconds and restarted for each of
two seller-side session models:

- **Link-scoped:** 60-second `max_session_seconds`, 20-second grace.
- **Account-like:** 7,200-second `max_session_seconds`, 20-second grace.

Both models have 100,000 msat credit (50,000 initial + 50,000 pay call) and no
meter charges during the gap. This arm uses the `Session` class rather than
real ecash; the actual blackholed transport is the FIPS container restart.

## Raw output

### Link-scoped (60-second deadline)

```text
before link=1 ping=True
gap=10s state=paid
gap=20s state=paid
gap=30s state=paid
gap=40s state=paid
gap=50s state=paid
gap=60s state=grace
gap=70s state=grace
gap=80s state=evicted
gap=90s state=evicted

after link=2 reconnected=True ping=True
session_final=evicted remaining_msat=100000
```

### Account-like (7,200-second deadline)

```text
before link=2 ping=True
gap=10s state=paid
...
gap=90s state=paid

after link=3 reconnected=True ping=True
session_final=paid remaining_msat=100000
```

## Interpretation

1. **Reconnecting changes the link id, not the buyer's identity.** Both arms
   came back and pinged successfully, with ids `1→2` and `2→3`. The session must
   be keyed to the authenticated npub, not a transient link or socket.
2. **The session deadline, not contact loss, caused the eviction.** The
   60-second model went `paid → grace` at the deadline and `evicted` after grace.
   That is correct for a link-scoped offer but wrong if an absent balloon pass
   is a normal transport property.
3. **An account/deferred-session model survives the same gap.** The longer
   deadline preserved paid state and credit without changing the FIPS client.
4. **A paused peer is not an unpaid one.** A pass gap should not erase credit
   or generate a fresh unverified "paid" state on reconnect; a monotonic durable
   account can be resumed, with only a new link handshake when necessary.

## Decision for D3/D4

Use a **prepaid account keyed by npub** for a balloon, with deadlines multiple
contact windows in length. Do not bind all credit to one continuously connected
FIPS link, and do not treat every silent pass as eviction. If TIP-11's link
session is used, grace must cover the whole offline period or a dormant/account
state must be introduced.

The 60-second link-deadline model failed this DTN requirement; the account-like
model passed it.

## Caveats and follow-ups

- One 90-second gap per model, not a replay of a real flight pass schedule.
- The session transition is the model under test; this arm did not redeem ecash
  or drive the full seller eviction path. Offline payment is measured separately
  in `OUTAGE-2026-11-10-offline-credit-settle.md`.
- No seller reboot: durable account recovery across a seller restart is future
  work and must use the journal's payer binding.
- Follow-up: test a 60-minute contact gap, a late renewal, and account resume
  with a fresh FIPS link and a wallet that never comes back.

## Artefacts

- `harness/exp-intermittent/intermittent.py`, compose and configs.
- `sidecar/tollgate_fips/session.py` (not modified).
