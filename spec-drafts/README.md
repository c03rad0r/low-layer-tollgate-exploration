# Spec drafts — target `OpenTollGate/tollgate`

Five ready-to-open PRs. None has been opened. The only public surface is
`OpenTollGate/tollgate`; nothing here is opened against `jmcorgan/fips`.

| # | File | Title | Depends on | Evidence |
|---|---|---|---|---|
| P1 | `01-endpoint-advertisement.md` | Endpoint advertisement, remove the port | — | Exp A, 01-TCP, fleet |
| P2 | `02-scope.md` | Session scope `link` / `e2e` | P1 | Exp A, PD, 01-TCP |
| P3 | `03-wire-byte-metering.md` | Wire-byte metering | P2 | Exp A, PD, PB |
| P4 | `04-pause-and-renewal.md` | Pause and renewal (four states) | P2, P3 | C, PB, PD, MP, B |
| P5 | `06-frame-gate.md` | Frame-level rate control (not authorisation) | P1, P3 | E-nft, E2, E4 |

Deferred:

- **05 payer binding** — P2PK, the journal and exposure are evidenced, but the
  encrypted preamble and msg1-ephemeral binding are still design
  (`docs/0003`). Do not draft normative text for them until a lab exercises the
  binding.

P5's nft rule is fully evidenced by E-nft/E2/E4. The real-AP `ndsctl` result
(Exp E) remains an open question in the draft, not a blocker for the nft rule;
it is a caveat, not a missing claim.

## How to open

From a clone of `OpenTollGate/tollgate`:

```sh
git checkout -b tip/endpoint-advertisement
# copy spec-drafts/01-endpoint-advertisement.md into the repo's TIP directory
# update its header to the repo's current TIP number and status
git add ... && git commit
gh pr create --title "TIP: endpoint advertisement; remove the port" \
  --body-file <(sed -n '1,120p' spec-drafts/01-endpoint-advertisement.md)
```

Repeat with `tip/scope`, `tip/wire-byte-metering`, `tip/pause-and-renewal`,
`tip/frame-gate`.
Update the TIP number and any repo-specific front matter first.

Before opening, check each draft against the repo's current TIP template. These
drafts are protocol text, not a patch against a known TIP directory.

## P4 caveat

P4 requires a per-peer forwarding role. Upstream FIPS 0.6.0-dev does not have
one; the local patch (b) does (`patches/0001-per-peer-forwarding.patch`,
`results/PB-2026-11-03-per-peer-forwarding.md`) and the capstone
(`results/PD-2026-11-03-pause-payment.md`) proves the shape. The patch is
unmerged. The FIPS ask is made out of band via Signal, never as a PR or issue.

## Verification status

- 112 sidecar tests pass.
- Exp A/B/C/E-nft/E2/E4/H/TCP/PB/PD/MP results are in `results/`.
- No PR or issue has been opened against `OpenTollGate/tollgate` yet.
- No PR or issue has been opened against `jmcorgan/fips` at any point.
