# Spec drafts — target `OpenTollGate/tollgate`

Five discussion-draft PRs, opened 2026-11-05. The only public surface is
`OpenTollGate/tollgate`; nothing here is opened against `jmcorgan/fips`.

| # | File | Opened as | PR | Branch | Depends on | Evidence |
|---|---|---|---|---|---|---|
| P1 | `01-endpoint-advertisement.md` | TIP-08 | [#51](https://github.com/OpenTollGate/tollgate/pull/51) | `tip/08-endpoint-advertisement` | — | Exp A, 01-TCP, fleet |
| P2 | `02-scope.md` | TIP-09 | [#52](https://github.com/OpenTollGate/tollgate/pull/52) | `tip/09-session-scope` | P1 | Exp A, PD, 01-TCP, MP |
| P3 | `03-wire-byte-metering.md` | TIP-10 | [#53](https://github.com/OpenTollGate/tollgate/pull/53) | `tip/10-wire-byte-metering` | P2 | Exp A, PD, PB |
| P4 | `04-pause-and-renewal.md` | TIP-11 | [#54](https://github.com/OpenTollGate/tollgate/pull/54) | `tip/11-pause-renewal` | P2, P3 | C, PB, PD, MP, B |
| P5 | `06-frame-gate.md` | `ETH-01` | [#55](https://github.com/OpenTollGate/tollgate/pull/55) | `eth/01-frame-gate` | P1, P3 | E-nft, E2, E4 |

Numbering was adapted on open: upstream already has open PRs claiming TIP-03
through TIP-07, so P1–P4 became TIP-08–11. P5 is a medium spec, named `ETH-01`
to match `WIFI-01` rather than taking a TIP number.

The files in this directory are the source drafts; the text actually opened is
the version committed on each branch under `OpenTollGate/tollgate` (or the
fork `c03rad0r/tollgate`). Differences are editorial plus the numbering, the
discussion-draft preamble, and corrections made while checking the drafts
against the reference source.

Deferred:

- **05 payer binding** — P2PK, the journal and exposure are evidenced, but the
  encrypted preamble and msg1-ephemeral binding are still design
  (`docs/0003`). Do not draft normative text for them until a lab exercises the
  binding.

P5's nft rule is fully evidenced by E-nft/E2/E4. The real-AP `ndsctl` result
(Exp E) remains an open question in `ETH-01`, not a blocker for the nft rule;
it is a caveat, not a missing claim.

## PR conventions used

- One new spec file per PR; no README index edit, so the five PRs do not
  conflict.
- Discussion-draft header in both the file and the PR body; no request to merge
  as-is.
- Evidence summarised in the PR body, because the lab repo is private. Logs and
  harness are offered on request.
- Cross-references name the other PRs by their adapted numbers.

## P4 caveat

P4 requires a per-peer forwarding role. Upstream FIPS 0.6.0-dev does not have
one; the local patch (b) does (`patches/0001-per-peer-forwarding.patch`,
`results/PB-2026-11-03-per-peer-forwarding.md`) and the capstone
(`results/PD-2026-11-03-pause-payment.md`) proves the shape. The patch is
unmerged and is not part of any PR. The FIPS ask is made out of band via
Signal, never as a PR or issue. TIP-11 says an implementation without the role
must declare itself non-conformant and fall back to durable eviction.

## Verification status

- 135 sidecar tests pass.
- Exp A/B/C/E-nft/E2/E4/H/TCP/PB/PD/MP results are in `results/`.
- Five PRs opened against `OpenTollGate/tollgate` (#51–#55), all discussion
  drafts; none merged.
- No PR or issue has been opened against `jmcorgan/fips` at any point.
