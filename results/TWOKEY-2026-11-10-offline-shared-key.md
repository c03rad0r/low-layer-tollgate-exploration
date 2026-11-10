# Result: TWOKEY — a shared P2PK key is not sufficient for offline acceptors

- **Date:** 2026-11-10 (run began 2026-11-09)
- **Operator:** c08rad0r
- **Experiment:** E-TWOKEY (docs/0019, decision D2)
- **Mint:** Nutshell 0.21.0, `FakeWallet`, test ecash only
- **Status:** completed mechanistic arms, n=1 token per arm

## Question

Can two offline acceptors share the same P2PK lock key without double-credit?
Does a per-acceptor key prevent it? Does inspecting the other acceptor's journal
close the hole?

## Setup

A real 50 sat TokenV4 P2PK+DLEQ token, three proofs, locked to one compressed
seller pubkey. Two independent journal/exposure databases (`s1` and `s2`)
represent two offline acceptors. The mint's keys are cached online, the mint is
stopped, then both acceptors verify offline and accept the token. The mint is
restarted and both attempt redemption with the same seller key.

A control arm checks the same token against another compressed pubkey. A sync
arm opens `s1`'s journal and asks whether it would already reject the proofs.

```sh
# The result uses the lab's private seller key; not its value.
bash harness/exp-twokey/run-twokey.sh /tmp/opencode/twokey-run
```

## Raw output

### Same key: both acceptors accept while the mint is down

```json
{
  "verify_ok": true,
  "problems": [],
  "proofs": 3,
  "s1": {
    "states": ["ACCEPTED", "ACCEPTED", "ACCEPTED"],
    "journal": ["RESERVED", "RESERVED", "RESERVED"],
    "exposure": "50000"
  },
  "s2": {
    "states": ["ACCEPTED", "ACCEPTED", "ACCEPTED"],
    "journal": ["RESERVED", "RESERVED", "RESERVED"],
    "exposure": "50000"
  }
}
```

### After reconnect: one redemption succeeds, the other fails

```json
{
  "s1": {"ok": true, "balance": "49 sat"},
  "s2": {
    "ok": false,
    "error": "Exception: Mint Error: proofs already spent (Code: 11001)"
  }
}
```

S1 received 49 sat from a 50 sat token (`input_fee_ppk=100`). S2's reserved
50,000 msat was credit risk with no redemption.

### Different key: offline verification rejects the lock

```text
verify_ok: false
p2pk_lock_ok: [false, false, false]
proof 2: locked to <actual seller pubkey>, not <other compressed pubkey>
proof 16: locked to <actual seller pubkey>, not <other compressed pubkey>
proof 32: locked to <actual seller pubkey>, not <other compressed pubkey>
```

### Journal sync would reject the second presentation

```json
[
  {"s1": "RESERVED", "s2_would_reject": true},
  {"s1": "RESERVED", "s2_would_reject": true},
  {"s1": "RESERVED", "s2_would_reject": true}
]
```

## Interpretation

1. **A shared key converts local replay into cross-acceptor double-credit.**
   Both local journals were empty, and both offline verifications were
   cryptographically correct. Only the mint's authority eventually distinguished
   them; this is not something independent acceptors can detect offline.
2. **A per-acceptor P2PK key is the right boundary for offline cash.** A token
   locked to the wrong seller key fails before any mint call. The purchaser
   needs the correct compressed key, but needs no shared journal.
3. **A fleet key is only viable with a shared/merged journal or an online
   check.** Opportunistic sync would reject this exact case, but its safety
   depends on every acceptor seeing the other reservations before granting
   credit. An unsynchronized contact is the double-credit window.
4. **The mint's later `SPENT` response limits loss but does not reverse it.**
   Any forwarding already granted by the losing acceptor was unpaid. An exposure
   cap and a small offline stint are therefore still necessary.

## Decision for D2

Use **per-balloon P2PK keys** for offline notes. Do not share one seller key
among independently operating offline relay balloons. A fleet key with journal
replication is a separate availability problem, not a shortcut.

Each balloon should publish the 33-byte compressed public key, not just an
x-only npub, in its offer. Nutshell 0.21.0 rejects x-only keys for this
purpose (`F-2026-11-03-offline-verify.md`).

## Caveats and follow-ups

- One 50 sat token with three proofs per arm; this is a deterministic replay
  demonstration, not a probability estimate. n=10 varied tokens remain optional.
- Only one mint and one seller key. No malicious mint, stolen balloon key,
  keyset rotation, or flash power loss beyond the separate crash test.
- The token was accepted while the mint was actually stopped; key caching was
  online before that, as deployment provisioning would be.
- Follow-up: time a fleet-journal merge against a real multi-pass contact
  schedule before considering any roaming fleet-key design.

## Artefacts

- `harness/exp-twokey/twokey.py`, `run-twokey.sh`.
- `results/F-2026-11-03-offline-verify.md` (offline P2PK/DLEQ prerequisite).
- `results/CRASH-2026-11-10-journal-ordering.md` (local journal crash ordering).
