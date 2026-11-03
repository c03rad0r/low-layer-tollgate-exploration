# Exp PB — per-peer transit forwarding (patch b)

Three-node chain A–B–C. B is the transit node and tree root; A and C are its
children. B runs the locally patched `fips-test:latest` image with the
`set_forwarding` control command.

## Run

```sh
harness/pause/run-pause.sh
harness/pause/run-pause.sh --down
```

Expected:

| Phase | Result |
|---|---|
| Chain up | A–B and B–C links |
| Baseline | A→C pass (via B), A→B pass |
| Block A at B | A→C **fail**, A→B **pass**, A–B link **preserved** |
| Allow A at B | A→C pass |

## Sidecar check

The sidecar is mounted at `/sidecar` in B. After the lab is up:

```sh
docker exec -e PYTHONPATH=/sidecar lt-pause-b python3 -c "
from tollgate_fips.control import UnixControl
from tollgate_fips.gate import FipsGate
g = FipsGate(control=UnixControl())
print(g.pause('<A npub>'))
"
```

`pause()` returns `mode='transit-blocked'` without disconnecting; `resume()`
clears it.

## Notes

- Raw ICMP did not trigger mesh discovery in this lab; the orchestrator warms
  the path with `fipsctl probe <C npub>` first.
- Identities were assigned so B is the tree root; a root A left C as a
  grandchild A never learned to route to.
- The patch is local and unmerged. Do not submit it to `jmcorgan/fips`.

## Result

`results/PB-2026-11-03-per-peer-forwarding.md`
