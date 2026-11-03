# Result: F (partial) — offline verification of a real P2PK+DLEQ token

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** F, verification half — can a seller verify a real Cashu token
  with the mint stopped?
- **Node(s):** local T14; Nutshell mint `lt-mint` (Docker)
- **Mint:** Nutshell 0.21.0, `FakeWallet` backend, no real funds
- **FIPS version / rev:** n/a (verification only)
- **TollGate commit:** n/a
- **Repo commit:** mint harness commit
- **Status:** **partial** — real DLEQ/P2PK verification and durable replay refusal
  pass offline; FIPS session continuity and Exp G are not done

## Question

`docs/0003` claims a payer can pay offline: DLEQ proves the mint signed the
proof and NUT-11 P2PK proves only the seller can redeem it. Can a real Nutshell
token satisfy both checks with the mint stopped, using only cached keyset keys?

## Setup

```sh
harness/mint/run-mint.sh
harness/mint/mint-token.sh 50 REPLACE_WITH_HEX_SEEDa4 /tmp/opencode/token.txt
```

The seller's compressed pubkey is derived from the Exp C/H FIPS nsec:

```
x-only npub decodes to : d05bdb05d951d3ddcbd289549a1ac03623415fbfaa2365127d7d4aec1a743ba4
full compressed key    : REPLACE_WITH_HEX_SEEDa4
```

The token is 50 sat, three proofs (2 + 16 + 32), DLEQ on every proof, P2PK
lock to the seller with `sigflag=SIG_INPUTS` and a locktime about 24 h out.
Keyset `01c476e6c92b2e6c`, `final_expiry: null`.

## Raw output

### Keyset / mint

```json
{"keysets":[{"id":"01c476e6c92b2e6c6a60aab4f74f9941f77689d9caa9ebffec08f887272443ccdf",
"unit":"sat","active":true,"input_fee_ppk":100,"final_expiry":null}]}
```

### Online verification

```
{
  "ok": true,
  "problems": [],
  "mint": "http://lt-mint:3338",
  "unit": "sat",
  "amount": 50,
  "proofs": [
    {"amount": 2,  "dleq_valid": true, "p2pk_lock_ok": true, "sigflag": "SIG_INPUTS"},
    {"amount": 16, "dleq_valid": true, "p2pk_lock_ok": true, "sigflag": "SIG_INPUTS"},
    {"amount": 32, "dleq_valid": true, "p2pk_lock_ok": true, "sigflag": "SIG_INPUTS"}
  ],
  "keyset_final_expiry": [null],
  "offline": true
}
```

(Elided: each proof's full nullifier and keyset id, and the locktime. The full
output is in `/tmp/opencode/verify-online.txt` at run time.)

### Offline verification, mint stopped

```
docker stop lt-mint
harness/mint/verify-offline.sh /tmp/opencode/token.txt /tmp/opencode/keys.json \
  REPLACE_WITH_HEX_SEEDa4
```

```
{
  "ok": true,
  "problems": [],
  "amount": 50,
  "proofs": [
    {"amount": 2,  "dleq_valid": true, "p2pk_lock_ok": true},
    {"amount": 16, "dleq_valid": true, "p2pk_lock_ok": true},
    {"amount": 32, "dleq_valid": true, "p2pk_lock_ok": true}
  ],
  "keyset_final_expiry": [null],
  "offline": true
}
```

Exit code 0 with the mint stopped. The verifier used only
`/tmp/opencode/keys.json`; no HTTP request was made.

### Repeat

A second token (1 sat) minted through `mint-token.sh` verified offline with the
same cache:

```
token written to /tmp/opencode/token1.txt (541 chars, 1 sat, P2PK to 03d0...)
ok: true, dleq_valid: true, p2pk_lock_ok: true, offline: true
```

### PaymentGate, journal and exposure (mint stopped)

`gate_token.py` turns the verified proofs into `PaymentProof`s and runs them
through `PaymentGate.accept()`, reopens the databases to simulate a restart,
replays, settles, and replays again:

```sh
docker stop lt-mint
docker run --rm -e PYTHONPATH=/app:/sidecar:/mint \
  -v /tmp/opencode:/data -v "$PWD/sidecar:/sidecar:ro" \
  -v "$PWD/harness/mint:/mint:ro" cashubtc/nutshell:latest \
  python3 /mint/gate_token.py /data/token.txt --keys-file /data/keys.json \
    --seller-pubkey REPLACE_WITH_HEX_SEEDa4 \
    --seller-npub npub16pdakpwe28famj7j392f5xkqxc35zhal4g3k2yna049wcxn58wjqsjm9wu \
    --mint http://lt-mint:3338 --db-dir /data/f-gate
docker start lt-mint
```

```
{
  "verify_ok": true,
  "offline": true,
  "amount": 50,
  "proofs": 3,
  "accepted": 3,
  "journal_states": ["RESERVED", "RESERVED", "RESERVED"],
  "exposure_outstanding_msat": "50000",
  "replay_before_settle": "ReservationInFlight",
  "settled": 3,
  "journal_states_after_settle": ["SETTLED", "SETTLED", "SETTLED"],
  "exposure_after_settle_msat": "0",
  "replay_after_settle": "AlreadySettled"
}
```

Exit code 0. The second process opened the same SQLite files and still refused
the replay; the refusal is durable, not in-memory.

## Measurements

| Metric | Value |
|---|---|
| Mint | Nutshell 0.21.0, FakeWallet |
| Token | 50 sat, 3 proofs (2/16/32) |
| DLEQ | valid on all proofs, online and offline |
| P2PK lock | seller `03d0...`, `SIG_INPUTS`, valid |
| Keyset `final_expiry` | null |
| Locktime | ≈ 24 h out |
| Online verification | pass |
| **Offline verification (mint stopped)** | **pass** |
| Repeat token (1 sat) | pass |
| Gate: proofs accepted | 3 (2 + 16 + 32 sat) |
| Journal after accept | RESERVED ×3 |
| Exposure after accept | 50,000 msat |
| Replay before settle | **ReservationInFlight** |
| After settle | SETTLED ×3, exposure 0 |
| Replay after settle | **AlreadySettled** |

## Interpretation

1. **Offline verification works on real ecash.** With the mint stopped, the
   seller can verify DLEQ and the P2PK lock from cached keyset keys. The same
   real proofs then go through `PaymentGate`/journal/exposure, and a restart
   still refuses the replay. The missing piece is the FIPS session: no link was
   kept paid across the outage.
2. **The x-only npub is not enough for NUT-11.** Nutshell rejected an x-only
   lock as "invalid compressed public key". The seller must use the 33-byte
   compressed key, which requires the parity bit. A FIPS identity has the nsec,
   so it can derive it; a sidecar that only sees the npub cannot. This is a
   concrete implementation requirement for the payer-binding TIP.
3. **The token carries no witness.** The P2PK condition is present, but the
   signature is added when the seller redeems. At acceptance the seller verifies
   the *lock condition* and its own ability to redeem; the payer's authorisation
   is the separate preamble signature over the msg1 ephemeral (`docs/0003`).
4. **`final_expiry` is null on the default keyset.** Exp G needs a rotated
   keyset with a short expiry, via the mint's management RPC. The journal's
   `keyset_admissible()` predicate is ready for it; the mint configuration is
   not.
5. **A real token survives the gate and the restart.** All three proofs went
   through `PaymentGate` to `RESERVED`, the exposure was exactly 50,000 msat,
   and a second process opening the same files refused the replay with
   `ReservationInFlight`. After settlement the replay became `AlreadySettled`.
   That is the durable half of Exp F at the payment layer; the link session was
   not involved.
6. **This is test money.** `FakeWallet` prints a fake invoice and marks it
   paid. The token is a bearer instrument but worth nothing. No Lightning node,
   no mainnet.

## Caveats

- One mint, two tokens, one keyset.
- No session, no journal, no exposure cap in this run. Those are unit-tested but
  not connected to a real proof yet.
- No NUT-07 spentness check (deliberately: this is the offline case). The
  journal is the local substitute; cross-seller double spend remains.
- `verify_token.py` runs inside the Nutshell image because it needs the `cashu`
  library. Production would import a pinned library into the seller rather than
  shell into a container.

## Follow-ups

- [x] Adapter from verifier JSON to `PaymentProof`/`PaymentGate`
      (`harness/mint/gate_token.py`); replay refused across a restart.
- [ ] Run Exp F end-to-end on a FIPS link: keep a session paid from the journal
      while the mint is stopped; restart the seller; confirm no replay and the
      session continues.
- [ ] Exp G: rotate a keyset with `final_expiry` and test the admission
      predicate.
- [ ] Add NUT-07 settlement and a batched worker.
- [ ] Record the compressed-pubkey requirement in the payer-binding TIP.

## Artefacts

- `harness/mint/run-mint.sh`
- `harness/mint/mint-token.sh`
- `harness/mint/verify_token.py`
- `harness/mint/verify-offline.sh`
- `harness/mint/gate_token.py`
- volumes `lt-mint-data`, `lt-wallet-data` (test ecash; destroy freely)
