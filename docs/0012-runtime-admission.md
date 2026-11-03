# 0012 — Runtime admission (patch a)

Status: implemented locally in `patches/0001-per-peer-forwarding.patch`; Rust
unit test plus four sidecar tests. Lab measurement: `results/A2-2026-11-03-runtime-admission.md`.

## The gap

FIPS 0.5.x/0.6.x admit a peer only from `peers.allow` / `peers.deny`. The
daemon polls those files on its 1 s tick, so a change is effective in
**756–984 ms** (Exp B) and not at all until the tick that follows the write.
Worse, the Phase 1 demo hit a deny storm: keeping a peer denied for 5–10 s left
the next handshake blackholed for more than 10 s after the file changed, even
though `acl show` was correct.

That latency is on the critical path of every re-admission: Exp C measured
**0.75–0.83 s** of the 2.7–2.9 s re-admit as ACL wait.

## The patch

```text
Node.acl_overrides: HashMap<NodeAddr, bool>   // true = allow, false = deny
```

`Node::authorize_peer` consults the override **before** the file ACL:

- `Some(true)` → admit, even if the files would deny;
- `Some(false)` → refuse, even if the files would allow;
- `None` → fall through to `PeerAcl::check` exactly as before.

Control surface:

```text
{"command": "set_admission",
 "params": {"npub": "npub1...", "action": "allow" | "deny" | "clear"}}
```

CLI:

```sh
fipsctl admission <peer> allow|deny|clear
```

`clear` removes the override, so the file ACL becomes authoritative again.

## Semantics

- Admission gates **new handshakes**. It never drops an established link; that
  is what `disconnect` and the forwarding policy are for. A gate that wants the
  link gone still disconnects.
- The override is **in memory**. A daemon restart loses it and falls back to the
  files. Durable eviction therefore still writes `peers.deny`; the override only
  removes the tick from the critical path.
- The override is **per node**, not per transport. A peer admitted on UDP is
  admitted on TCP.
- `allow` does not create a link. The buyer still has to dial (or `auto_connect`
  has to retry); the measurement separates command latency from handshake
  latency.

## Gate ordering

`FipsGate.admit` / `deny` set the runtime override **and** write the file:

```text
admit:  set_admission allow  ->  peers.allow write
deny:   set_admission deny   ->  peers.deny write
evict:  set_admission deny   ->  peers.deny write  ->  disconnect
```

Because the runtime deny is effective on the next handshake, `evict` no longer
waits for the ACL tick before disconnecting. Re-admission likewise skips the
tick: `admit` sets the override, and the next handshake is admitted. The file
write still happens, so the state survives a restart.

If the control command is absent (stock FIPS), `set_admission` fails and the
gate falls back to the old file + wait path. `EvictResult.mode` reports
`runtime+deny+disconnect` when the override was used and `deny+disconnect`
otherwise.

## What it does not solve

- **Restart durability.** An override set and never written to the file is lost
  on restart. The gate always writes both; a human using `fipsctl admission`
  alone is choosing runtime-only.
- **Existing links.** A denied peer keeps its current link until disconnected,
  which is useful (pause) but means `admission deny` alone is not eviction.
- **Audit.** The only record is the `API runtime admission changed` log line.
  A production seller should persist the last decision per peer.
- **The tree.** Re-parenting and routing are unaffected; this is L1 admission
  only.

## Tests

- Rust: `runtime_admission_override_beats_the_file_acl` — runtime deny over a
  file allow, runtime allow over a file deny, `clear` falls back, unknown action
  refused.
- Sidecar: runtime allow/deny recorded alongside the file write; evict with the
  override skips the ACL wait; evict without the command falls back to the wait.

## Next

- Measure the saved millis in the lab (`results/A2`).
- Feed the runtime path into `pause()`'s crude fallback so the deny window is
  short even without patch (b).
- Persist the last runtime decision so a restart does not silently widen
  admission.
