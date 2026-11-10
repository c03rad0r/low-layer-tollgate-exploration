# Result: BIND — FIPS identifies the presenter; the journal rejects replay

- **Date:** 2026-11-10
- **Operator:** c08rad0r
- **Experiment:** E-BIND (docs/0019, decisions D2/D3)
- **Nodes:** `lt-bind-a`, `lt-bind-b`, `lt-bind-c`, private Docker bridge
- **FIPS:** 0.6.0-dev (rev `2ba790b221`)
- **Status:** completed five-message application-replay arm

## Question

Can the seller determine which FIPS npub presented a P2PK token? Can a second
peer replay the token and be credited, either by claiming the original payer or
claiming itself?

## Setup

A is one FIPS peer, C another; B runs a UDP service on IPv6/2122 locally. Peers
send a JSON PAY over the established FIPS link with a real opaque token string
and an optional `declared_payer`. B reads the source FIPS IPv6 address and maps
it to the authenticated peer via `fipsctl show peers` (peer `ipv6_addr` →
`npub`, `link_id`). A nullifier-style used-token journal deduplicates by the
bearer token rather than by a claimed identity or message sequence.

The sequence sends: A's first PAY; C replaying the same PAY as A; C presenting
the same token as itself; A retrying after a simulated ACK loss; A's new token.
No redemption occurs, so this is an application/binding experiment, not a
ciphertext double-spend proof.

## Raw output

Condensed from `harness/exp-bind/server-output.json` (token values omitted):

| Step | Actual FIPS-bound peer | Declared payer | Action | Credit after step |
|---|---|---|---|---:|
| 1: A, token 1 | A (`link_id=4`) | A | ACCEPT | A 5 sat |
| 2: C, token 1 | C (`link_id=3`) | A | REPLAY_REJECT | A 5 sat, C 0 |
| 3: C, token 1 | C (`link_id=3`) | C | REPLAY_REJECT | A 5 sat, C 0 |
| 4: A retries token 1 | A (`link_id=4`) | A | REPLAY_REJECT | A 5 sat |
| 5: A, token 2 | A (`link_id=4`) | A | ACCEPT | A 10 sat |

Example records:

```json
{
  "token_prefix": "cashuBo2F0ga",
  "source_ipv6": "fdaf:2120:681b:b711:4fd2:3b61:5d4a:36a7",
  "bound_npub": "npub1pqf3mx4ayr68ldz39l3unrgkn0rhe8ch7437wv6pav6tpj0777lsrznlup",
  "link_id": 3,
  "action": "REPLAY_REJECT"
}
```

The claimed declaration never overrode the link-derived peer; the second and
third steps produced no new credit, even with different declared npubs.

## Interpretation

1. **FIPS provides a usable presenter binding before any Cashu-specific
   signature check.** B did not infer identity from the token string, an IP
   address, or a message field. It derived it from an authenticated FIPS peer.
2. **A second presenter does not get a new session from a replay.** The journal
   prevents credit whether the replay names A or C, and also deduplicates A's
   honest retry after an ACK loss. Session identification without the journal
   would be just as unsafe as crediting every receipt.
3. **Credit should follow the sender of PAY, with a nullifier reservation as
   the gate.** For an app relay, the minimal secure rule is "verify the token,
   bind it to this authenticated npub, reserve it before granting service". A
   mismatching declared payer is rejected; declarations are not authentication.
4. **This does not implement the complete payer-binding design.** No encrypted
   seller preamble or msg1-ephemeral was exercised. Those remain needed for the
   deferred design in `docs/0003-payer-binding.md`, especially if payment is
   relayed rather than sent directly to the seller.

## Decision for D2/D3

Use an npub-bound prepaid account for each balloon and bind PAY to the
authenticated FIPS peer that sent it. Do not publish a service that credits by
token alone or trusts a `payer_npub` field. The proof/nullifier reservation must
cross client retries and must precede credit.

## Caveats and follow-ups

- Two direct peers, not a relayed multi-hop payment exchange.
- Token strings are opaque here: offline P2PK verification is covered in
  TWOKEY/OUTAGE, not duplicated by this harness.
- Link IDs changed only because a fresh lab run was used; no rebind/roaming test.
- Follow-up: send PAY via a third FIPS node and confirm the end-to-end identity
  remains the payer's rather than the relay hop's.

## Artefacts

- `harness/exp-bind/` — FIPS-native application message sender and listener.
- `docs/0003-payer-binding.md` — deferred cryptographic binding design.
