# AGENTS.md — how we work in this repo

## Upstream interaction policy

- **All protocol PRs and issues go to `OpenTollGate/tollgate`.**
  That repository is the canonical home of the TollGate protocol.
- **Do not open pull requests or issues against `jmcorgan/fips`.**
  The maintainer does not want public interaction of that kind. This is a
  standing instruction, not a preference of the moment.
- If we find something material in FIPS — a bug, a missing hook, a security
  issue — we do **not** file it publicly. We write it up in `results/`,
  and the operator raises it out of band via Signal, only after the
  experiment backing it is complete and reproducible.
- Local FIPS changes live in `patches/` as unmerged patch files. Never push
  them to a public fork, never open a PR with them.

## Experiment hygiene

- Every experiment writes `results/<id>-<date>.md` **before** it is summarised
  anywhere else. Raw stdout first, interpretation second.
- Record: date, operator, node names, FIPS version and rev, TollGate commit,
  exact commands.
- No experiment touches mainnet funds. Test mints only.
- Check disk free space before writing to any fleet node.

## Repo conventions

- One directory per experiment under `experiments/`.
- Design notes under `docs/`, numbered.
- Spec drafts under `spec-drafts/`, one file per PR.
- `CHECKLIST.md` is the live tracker; update it in the same commit as the work.
