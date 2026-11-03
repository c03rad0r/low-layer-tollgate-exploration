# 0003 — Payer binding

Status: design. Evidence pending Phase 3 (Exp F).

## The problem

Payment happens *before* admission, therefore before the Noise link exists.
Anything sent at that point is plaintext unless we make it otherwise. And a
bearer token is paper: whoever holds it can spend it.

## The construction

1. **Encrypt to the seller's static key.** The payer already knows the seller's
   npub — FIPS IK requires the responder's static key to dial. ECDH to it. No
   one on the path can read the token.
2. **Lock the proof to the seller.** NUT-11 P2PK with `data` = seller pubkey and
   `sigflag` = `SIG_ALL`. Even if the ciphertext leaks, only the seller can
   redeem.
3. **Sign with the payer's static key** over a payload containing:
   token, seller npub, payer npub, transport type, **the msg1 ephemeral public
   key**, `issued_at`, and claimed steps. The signature proves the payer
   controls the npub; the ephemeral binding proves *which handshake attempt*
   it authorises.
4. **Local nullifier journal.** The seller records the nullifier the moment it
   accepts, before granting credit. State machine:
   `RESERVED → SETTLED | SPENT`, fsync'd.
5. **Exposure cap.** Per peer, per mint, per unit: the maximum face value of
   unsettled tokens. Cross-seller double spend is residual risk, bounded here.

## Why the msg1 ephemeral is the nonce

FIPS already remembers the ephemeral key of every msg1 it answered or refused,
because "a copy of one still authenticates after its cycle has ended". Binding
the payment to it means a captured preamble cannot be replayed onto another
link, and the seller gets replay protection for free from machinery that
already exists.

## What P2PK does and does not buy

| Question | Answered by | Round trip |
|---|---|---|
| Is this proof mint-signed? | mint pubkey + DLEQ | no |
| May the seller spend it? | NUT-11 P2PK | no |
| Has it been spent? | NUT-07 `/checkstate` | **yes** |

NUT-11's own use-cases list says locked ecash supports "final offline-receiver
payments that can't be double-spent when combined with an offline signature
check mechanism like DLEQ proofs". Read that carefully: offline *authenticity*,
not offline *spentness*. The journal is what closes the gap, and only for the
replay case.

## Threat table

| Attack | Caught by |
|---|---|
| Path observer reads the token | encryption to seller key |
| Path observer redeems first | P2PK to seller |
| Payer replays the same token to the same seller | local journal |
| Payer gives one token to two sellers | **not caught**; capped by exposure |
| Payer claws back via `refund` after `locktime` | journal must track locktime and refund keys |
| Seller restarts and forgets | fsync before credit; journal is correctness, not cache |

## Journal requirements

- Keyed by `(mint_url, unit, keyset_id, nullifier)`.
- Durable before credit: WAL + `synchronous=EXTRA`, or an explicit fsync.
- Records `keyset_id` and `final_expiry`, because after `final_expiry` the mint
  may delete its nullifier set (NUT-02) and the journal becomes the only
  surviving record.
- Settlement is a background job; it never blocks admission.
