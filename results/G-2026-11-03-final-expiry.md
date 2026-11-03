# Result: G — a real keyset `final_expiry`

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** G — what happens at NUT-02 `final_expiry`?
- **Node(s):** local T14; Nutshell mint `lt-mint`
- **Mint:** Nutshell 0.21.0, `FakeWallet`, no real funds
- **FIPS version / rev:** n/a
- **TollGate commit:** n/a
- **Repo commit:** Exp G commit
- **Status:** pass (predicate verified; mint behaviour recorded)

## Question

`docs/0009` treats `final_expiry` as a **settlement deadline**: a seller must
reject a proof whose keyset expires inside the settlement window, because after
expiry the mint may delete the nullifier and the seller could lose the value.
Does a real Nutshell mint advertise the field, enforce it, and does the
receiver predicate behave as specified?

## Setup

Nutshell has no management RPC for `final_expiry`, so the lab sets it in the
mint's SQLite store while the daemon is stopped:

```sh
harness/mint/expiry.py
```

Steps:

1. Start the mint; mint a plain 10 sat token (unlocked, so a receiver can later
   attempt to spend it).
2. Stop the mint; `UPDATE keysets SET final_expiry = now + 120`.
3. Restart; read `/v1/keysets`.
4. Evaluate `keyset_admissible(final_expiry, settlement_window, now)` for a
   3,600 s and a 1 s window.
5. Wait past `final_expiry`; read `/v1/keysets` again.
6. Try to spend the 10 sat token at the mint with a fresh wallet.
7. Restore `final_expiry = NULL`.

## Raw output

```
keysets before:
[{"id":"01c476e6c92b2e6c...","active":true,"final_expiry":null}]

keysets after:
[{"id":"01c476e6c92b2e6c...","active":true,"final_expiry":1793721256}]

admissible(3600s)=False  admissible(1s)=True

waiting 123s for final_expiry

keysets after expiry:
[{"id":"01c476e6c92b2e6c...","active":true,"final_expiry":1793721256}]

spend after expiry: ok=True
```

## Measurements

| Check | Result |
|---|---|
| Mint advertises `final_expiry` | yes (exact value written) |
| Keyset still `active` after expiry | **yes** |
| `keyset_admissible(expiry, 3600 s)` at now | **false** (rejected) |
| `keyset_admissible(expiry, 1 s)` at now | true (accepted) |
| Spend after `final_expiry` | **accepted by the mint** |
| DLEQ/P2PK verification | unaffected (Exp F) |

## Interpretation

1. **The receiver predicate is load-bearing.** Nutshell 0.21.0 keeps the keyset
   active and accepts a spend after `final_expiry`. A seller that trusts the
   mint to refuse expired keysets would be wrong. `keyset_admissible` is the
   only local guard, and it must be applied at admission.
2. **A settlement window changes the answer.** With a 3,600 s window the proof
   is refused before expiry; with a 1 s window it is accepted. The seller must
   choose a window that covers its settlement latency, not a universal number.
3. **`final_expiry` is not a session clock.** Nothing about the link session
   should key off it; the local monotonic deadline remains the authority
   (`docs/0004`). This run changes only the money side.
4. **NUT-02 is permissive, not enforcing.** "May irrevocably remove" is not
   "must refuse". Implementations differ; a protocol cannot assume the stronger
   reading.
5. **The DB edit is a lab tool, not a deployment path.** A production mint
   rotation would set `final_expiry` when retiring a keyset; the lab does the
   equivalent directly because Nutshell exposes no RPC.

## Caveats

- One mint version (Nutshell 0.21.0, September build). Other mints may enforce
  expiry at rotation or delete nullifiers.
- The keyset was not rotated; `active` stayed true. A real rotation would mark
  it inactive and add a successor.
- Plain token, no P2PK lock, because the point was the mint's post-expiry
  behaviour, not the seller's redemption.
- `final_expiry` was restored to `NULL` afterwards for later labs.

## Follow-ups

- [ ] Repeat with a rotated keyset (`active=false`) and a successor.
- [ ] Compare against another mint implementation (CDK) if one is available.
- [ ] Settle a payment across the expiry boundary with the exposure cap, to size
      the settlement window empirically.

## Artefacts

- `harness/mint/expiry.py`
- `docs/0009-nullifier-journal.md` (predicate semantics)
