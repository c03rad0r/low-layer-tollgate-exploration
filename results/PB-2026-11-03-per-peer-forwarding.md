# Result: PB — per-peer transit forwarding policy (patch b)

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** patch (b) — can FIPS block one peer's **transit** while keeping
  its link, Noise session and local path?
- **Node(s):** `lt-pause-a`, `lt-pause-b`, `lt-pause-c` (chain A–B–C)
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`) + local unmerged patch
- **TollGate commit:** n/a
- **Repo commit:** patch (b) commit
- **Status:** pass in the lab; local patch, not upstream

## Question

Every earlier result pointed at the same missing hook: FIPS can admit a peer or
disconnect it, but cannot stop one peer's forwarding while keeping the link.
This experiment implements and tests that hook.

## Patch

`patches/0001-per-peer-forwarding.patch` (90 added lines, 4 files):

- `Node.forwarding_blocked: HashSet<NodeAddr>`;
- control command `set_forwarding {"npub": ..., "allow": bool}`;
- in `handle_session_datagram`, a transit datagram from a blocked peer is
  dropped **before** next-hop resolution;
- local delivery (`dest == my_addr`) is deliberately untouched, so the peer
  keeps its link, Noise session and a path to the seller;
- the set is independent of the peer table, so the block survives a
  disconnect/reconnect until an explicit allow.

The patch is local and unmerged. It is not submitted to `jmcorgan/fips`; any
upstream conversation goes out of band via Signal after reproducible results.

## Setup

Chain A–B–C. B is the transit node and the tree root; A and C are its children.
All use the patched `fips-test:latest` image. A pings C through B; A↔B traffic
is local delivery at B.

A raw ICMP ping did not trigger FIPS discovery in this lab, so the orchestrator
warms the path with `fipsctl probe <C npub>` before the baseline. The probe
opens and tears down a diagnostic session and populates A's identity cache and
route.

```sh
harness/pause/run-pause.sh
```

## Raw output

```
a=npub1hs6dzx86tn2c7mt3wntw2tt7m6seyua78pwfhagkk08v2yur9m0smvtmad b=npub1thgwcxk5x45r9vusqzksmxnewfkgzhrdf4dlnc75ky96g6swnhlszjzgrw c=npub1pqf3mx4ayr68ldz39l3unrgkn0rhe8ch7437wv6pav6tpj0777lsrznlup c_addr=fdaf:2120:681b:b711:4fd2:3b61:5d4a:36a7
chain up: a-b=669 ms b-c=88 ms
baseline: a->c=True a->b=True
block response: {"status": "ok", "data": {"forwarding": "blocked", "npub": "npub1hs6dzx86tn2c7mt3wntw2tt7m6seyua78pwfhagkk08v2yur9m0smvtmad", "peer": "edc60ce11628233dce5a346e174da5e3"}}
blocked: a->c=False a->b=True link_a_b=True
allow response: {"status": "ok", "data": {"forwarding": "allowed", "npub": "npub1hs6dzx86tn2c7mt3wntw2tt7m6seyua78pwfhagkk08v2yur9m0smvtmad", "peer": "edc60ce11628233dce5a346e174da5e3"}}
allowed: a->c=True a->b=True

{
  "date": "2026-11-03",
  "fips_version": "0.6.0-dev (rev 2ba790b221)",
  "nodes": {
    "a": "npub1hs6dzx86tn2c7mt3wntw2tt7m6seyua78pwfhagkk08v2yur9m0smvtmad",
    "b": "npub1thgwcxk5x45r9vusqzksmxnewfkgzhrdf4dlnc75ky96g6swnhlszjzgrw",
    "c": "npub1pqf3mx4ayr68ldz39l3unrgkn0rhe8ch7437wv6pav6tpj0777lsrznlup"
  },
  "chain": {"a_b_ms": 669, "b_c_ms": 88},
  "baseline": {"a_to_c": true, "a_to_b": true},
  "block": {
    "response": {"status": "ok", "data": {"forwarding": "blocked"}},
    "a_to_c": false,
    "a_to_b": true,
    "link_a_b_preserved": true
  },
  "allow": {
    "response": {"status": "ok", "data": {"forwarding": "allowed"}},
    "a_to_c": true,
    "a_to_b": true
  }
}
```

### Sidecar validation (patched seller)

The sidecar's own `FipsGate.pause()`/`resume()` were run inside the patched
seller container, not just the lab's raw control client:

```
PauseResult(paused=True, mode='transit-blocked',
            warning='transit blocked; the link, Noise session and local delivery are preserved',
            acl_wait_ms=None)
a->c: 2 transmitted, 0 received, 100% packet loss
a->b: 1 transmitted, 1 received, 0% packet loss
resume: {'forwarding': 'allowed', ...}
a->c: 2 transmitted, 2 received, 0% packet loss
```

The sidecar path is covered by 5 unit tests with a fake control client.

## Measurements

| Metric | Value |
|---|---|
| Chain links | A–B 669 ms, B–C 88 ms |
| Baseline A→C | pass (via B) |
| Baseline A→B | pass (local) |
| Block command | `status: ok`, `forwarding: blocked` |
| **A→C after block** | **fail** |
| **A→B after block** | **pass** |
| **A–B link after block** | **preserved** |
| Allow command | `status: ok`, `forwarding: allowed` |
| A→C after allow | pass |
| A→B after allow | pass |
| Sidecar `FipsGate.pause()` | `transit-blocked`, no disconnect |
| Sidecar `FipsGate.resume()` | `forwarding: allowed` |
| Patch size | 90 lines, 4 files |

## Interpretation

1. **Patch (b) makes pause implementable, and the sidecar uses it.** A peer can
   be stopped from using this node as transit while its link, Noise session and
   local path remain. `FipsGate.pause()` returns `transit-blocked` and does not
   disconnect; `resume()` restores transit. That is the shape `grace` needs:
   forwarding blocked, payment lane open.
2. **Local delivery is the payment lane.** A→B still works while A→C is
   blocked. The seller can keep serving the buyer, and the buyer can keep paying
   over a path that terminates at the seller, without being able to use the
   seller as free transit to the rest of the mesh.
3. **The block is durable across a reconnect.** The set is keyed on NodeAddr and
   independent of the peer table, so a peer that disconnects and comes back is
   still blocked until `allow=true`. That is the default a gate wants.
4. **A raw ICMP packet did not trigger discovery in this lab.** `fipsctl probe`
   populated the identity cache and route; after that the baseline worked. This
   is a lab convergence detail, not a property of the patch, but it matters for
   an automated gate: the sidecar may need to warm a path before the first
   transit packet, or the session layer should initiate lookup on its own.
5. **No blocked-byte counter.** The patch logs the drop at `debug` but does not
   add a metric. A production gate needs `drop_policy_blocked_{packets,bytes}`;
   the local patch is deliberately minimal.

## Caveats

- Local, unmerged patch. Not upstream, not public, not a PR.
- One run, one chain, one root order. Repeat with different roots and a longer
  chain.
- No payment traffic in this run; that integration is the next step.
- No CLI subcommand: the lab sends the control command over the raw Unix
  socket. A `fipsctl set-forwarding` command is a follow-up.
- Only transit is blocked. If the seller's own local service is the product,
  the policy needs a separate "local delivery" role.

## Follow-ups

- [x] Patch (b): per-peer transit forwarding policy.
- [ ] Add `drop_policy_blocked_{packets,bytes}` metrics.
- [ ] Add `fipsctl set-forwarding` so the sidecar does not need a raw socket.
- [x] Wire `FipsGate.pause`/`resume` to `set_forwarding` via `UnixControl`
      (5 tests); validated against the patched seller container.
- [x] Re-run the payment demo on a chain with a service behind the seller;
      pause replaces the cut end-to-end (`PD-2026-11-03-pause-payment.md`).
- [ ] Repeat the pause test with payment traffic and over TCP/Ethernet.
- [ ] Prepare the out-of-band Signal write-up (do not send until the result is
      reproducible).

## Artefacts

- `patches/0001-per-peer-forwarding.patch`
- `harness/pause/` (compose, configs, control client, orchestrator)
- `harness/pause/control.py`
