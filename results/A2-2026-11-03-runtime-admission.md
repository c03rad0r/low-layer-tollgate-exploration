# Result: A2 — runtime admission vs the ACL-file tick

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** patch (a) — can admission change on the next handshake instead
  of the next 1 s ACL tick?
- **Node(s):** `lt-exp-c-seller` (passive), `lt-exp-c-buyer` (`auto_connect`)
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local patch (a)
- **TollGate commit:** n/a
- **Repo commit:** patch (a) commit
- **Status:** pass; local unmerged patch

## Question

Exp B measured the ACL-file reload at 756–984 ms, and the Phase 1 demo hit a
deny storm that blackholed the next handshake. Does a runtime admission override
remove that wait from re-admission, and does it fall back to the files when
cleared?

## Patch

Same local, unmerged patch file as (b):

- `Node.acl_overrides: HashMap<NodeAddr, bool>`
- `authorize_peer` checks the override before `PeerAcl::check`
- control command `set_admission {npub, action: allow|deny|clear}`
- CLI `fipsctl admission <peer> allow|deny|clear`
- Rust test `runtime_admission_override_beats_the_file_acl`

Runtime admission gates **new handshakes**. It does not drop an established
link; the experiment disconnects before each measurement.

## Setup

Two-node UDP pair from `harness/exp-c`. The seller starts with a file allow; the
buyer auto-connects. Each phase:

1. write/deny or set the override;
2. disconnect the buyer;
3. force one explicit `fipsctl connect` from the buyer;
4. wait for both sides to report the peer again.

Payment is not involved.

```sh
harness/exp-c/run-admission.sh
```

Three clean runs, each from a fresh compose project.

## Measurements

| Run | File reallow | Runtime re-admit | File re-admit (incl. ACL wait) | **Saved** | Runtime deny held | Clear fell back |
|---|---|---|---|---|---|---|
| 1 | 708 ms | 2,735 ms | 3,908 ms | **1,173 ms** | yes | yes |
| 2 | 599 ms | 3,190 ms | 4,594 ms | **1,404 ms** | yes | yes |
| 3 | 786 ms | 3,062 ms | 3,923 ms | **861 ms** | yes | yes |

| Metric | Range (n=3) |
|---|---|
| File ACL reallow | 599–786 ms |
| Runtime `deny` command | 55–400 ms (one outlier) |
| Runtime `allow` command | 50–84 ms |
| **Runtime re-admit (allow → link)** | **2,735–3,190 ms** |
| **File re-admit (ACL wait + handshake)** | **3,908–4,594 ms** |
| **Saved per re-admission** | **861–1,404 ms** (median 1,173) |
| Runtime deny holds (2 s) | 3/3 |
| `clear` falls back to file deny | 3/3 |

The file re-admit number includes the ACL write wait **and** the handshake. The
runtime number is only the handshake, because the override is already effective
when `fipsctl admission allow` returns.

## Interpretation

1. **Runtime admission removes the tick from re-admission.** 0.86–1.40 s saved
   per re-admission, consistent with Exp B's 0.76–0.98 s ACL latency plus
   scheduling. The handshake dominates the rest (~2.7–3.2 s in this lab).
2. **Deny is effective on the next handshake.** After `admission deny`, a forced
   connect never formed a link in the 2 s window, every run. There is no 1 s gap
   and no deny-storm blackhole.
3. **`clear` really returns authority to the files.** After `clear`, the file
   was still deny-all and the forced connect was refused in 3/3 runs. The
   override is not a sticky shadow ACL.
4. **It is a latency patch, not a durability patch.** The override is in memory;
   a restart falls back to the files. `FipsGate.evict` therefore writes
   `peers.deny` as well, and uses the override only to close the window before
   the file lands.
5. **Command cost is small but not free.** `allow` took 50–84 ms (process +
   control round trip); one `deny` outlier took 400 ms, likely scheduling. Either
   is far below the tick.

## Caveats

- One pair, UDP, three runs. The file number is tick-phase dependent (Exp B's
  range); the runtime number is not.
- The handshake (~2.7–3.2 s) is larger than Exp C's re-admit link component
  (~1.9 s). Treat `saved` as the ACL component, not a full re-admit claim.
- Admission gates new handshakes only. An established link keeps forwarding
  until `disconnect` or the forwarding policy blocks transit.
- Local, unmerged patch. Not submitted to `jmcorgan/fips`; the upstream ask is
  out of band.

## Follow-ups

- [ ] Repeat over TCP.
- [ ] Persist the last runtime decision so a restart does not silently widen
      admission.
- [ ] Use the runtime path in `pause()`'s crude fallback so the deny window is
      short even without patch (b).
- [ ] Add the override to `acl show` for operator visibility.

## Artefacts

- `0001-per-peer-forwarding.patch` (private patches repo, not published)
- `harness/exp-c/admission.py`
- `harness/exp-c/run-admission.sh`
- `docs/0012-runtime-admission.md`
