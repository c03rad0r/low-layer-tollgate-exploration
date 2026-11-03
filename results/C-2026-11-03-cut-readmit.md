# Result: C — cut and re-admit (two-node FIPS lab)

- **Date:** 2026-11-03
- **Operator:** c08rad0r
- **Experiment:** C — cost of cut and re-admit; does the payment lane survive?
- **Node(s):** `lt-exp-c-seller`, `lt-exp-c-buyer` (private Docker bridge)
- **FIPS version / rev:** 0.6.0-dev (`2ba790b221`)
- **TollGate commit:** n/a
- **Repo commit:** durable-evict commit + lab harness
- **Status:** pass for cut/re-admit; **partial** for payment (no mint)

## Question

FIPS 0.5.x/0.6.x have exactly two levers: ACL admission at L1 and
`fipsctl disconnect` at L2. There is no per-peer forwarding role, so the only
way to act on exhaustion is to cut the link. Does the cut hold, what does it
cost, and does the in-band payment path survive?

## Setup

Two-node UDP lab on a private Docker bridge, built from the pinned FIPS tree
`2ba790b` (`0.6.0-dev`). The seller is **passive**: no peer entry, so it never
dials. The buyer auto-connects to `seller:2121`. The seller's ACL is the gate:
`peers.deny` contains `ALL`, `peers.allow` contains the buyer npub
(strict allowlist, mode `allow_then_deny_all`).

```sh
harness/exp-c/run-exp-c.sh
```

Test identities are derived from the test mesh name
`low-layer-tollgate-exp-c`; they are not secrets.

Traffic: 40 ICMPv6 frames with 1200-byte payloads from buyer to seller over the
FIPS link. Metering is the sidecar's per-link delta, all frames, FMP bytes.

Two runs:

- **Run 1** — before the sidecar's `evict` was made durable. The crude pause
  did a bare `disconnect`.
- **Run 2** — after `evict` was changed to **deny → wait for ACL → disconnect**.
  This is the current code.

## Raw output — Run 1 (bare disconnect)

```
seller npub=npub16pdakpwe28famj7j392f5xkqxc35zhal4g3k2yna049wcxn58wjqsjm9wu version=0.6.0-dev (rev 2ba790b221) addr=fd1e:86e5:33db:1aea:ff3:cbe8:bd7b:b9bb
buyer  npub=npub16584pelypd8qd0u7vyfye7vam3jtschup0heyuez20m59xlmhzks2y5wfa version=0.6.0-dev (rev 2ba790b221)
ACL allow npub16584pelypd8qd0u... effective in 613 ms (mode=allow_then_deny_all)
link up: link_id=1 (waited 113 ms)
ping before: ok=True loss=0.0%
traffic: ping loss=0.0% metered in=35299 out=34975 total=70274 cost=70.274000 msat
session: allotment=35.137000 msat used=70.274000 msat state=grace forwarding=False
pause(strict): UNSUPPORTED — FIPS has no per-peer forwarding role. The link can only be kept (and forwarding continued) or disconnected. Use allow_disconnect=True for the crude Phase 1 fallback.
pause(crude): disconnect; disconnect command returned in 46 ms
  warning: pause degraded to disconnect: the link and the payment lane are gone. This is the evidence for FIPS patch (b) and P4.
link down: seller_observed=True buyer_observed=True at 777 ms
link back: mode=auto link_id=2 total=6756 ms after_down=5979 ms
link_id changed=True
ACL deny: effective in 812 ms
ACL deny held for 3.0s: seller_link=False buyer_link=False
ACL allow: effective in 819 ms; link re-admitted mode=explicit in 3131 ms (total 3950 ms)
```

## Raw output — Run 2 (durable evict, current code)

```
seller npub=npub16pdakpwe28famj7j392f5xkqxc35zhal4g3k2yna049wcxn58wjqsjm9wu version=0.6.0-dev (rev 2ba790b221) addr=fd1e:86e5:33db:1aea:ff3:cbe8:bd7b:b9bb
buyer  npub=npub16584pelypd8qd0u7vyfye7vam3jtschup0heyuez20m59xlmhzks2y5wfa version=0.6.0-dev (rev 2ba790b221)
ACL allow npub16584pelypd8qd0u... effective in 925 ms (mode=allow_then_deny_all)
link up: link_id=1 (waited 92 ms)
ping before: ok=True loss=0.0%
traffic: ping loss=0.0% metered in=39274 out=39274 total=78548 cost=78.548000 msat
session: allotment=39.274000 msat used=78.548000 msat state=grace forwarding=False
pause(strict): UNSUPPORTED — FIPS has no per-peer forwarding role. The link can only be kept (and forwarding continued) or disconnected. Use allow_disconnect=True for the crude Phase 1 fallback.
cut(non-durable): fipsctl disconnect returned in 49 ms
link down: seller_observed=True buyer_observed=True at 764 ms
link back WITHOUT payment: mode=auto link_id=2 total=6616 ms after_down=5852 ms
pause(crude/durable): mode=deny+disconnect acl_wait=978 ms cmd=1099 ms
  warning: pause degraded to eviction: the link and the payment lane are gone, and the npub is denied so auto_connect cannot bring the link back without a new admission. This is the evidence for FIPS patch (b) and P4.
durable link down: seller_observed=True buyer_observed=True at 2142 ms
deny held for 3.0s: seller_link=False buyer_link=False
ACL allow: effective in 829 ms; link re-admitted mode=auto in 1873 ms (total 2701 ms) link_id=3

{
  "date": "2026-11-03",
  "fips_version": "0.6.0-dev (rev 2ba790b221)",
  "seller_npub": "npub16pdakpwe28famj7j392f5xkqxc35zhal4g3k2yna049wcxn58wjqsjm9wu",
  "buyer_npub": "npub16584pelypd8qd0u7vyfye7vam3jtschup0heyuez20m59xlmhzks2y5wfa",
  "acl": {"initial_allow_ms": 925, "allow_readmit_ms": 829},
  "exp_c": {
    "link_id_before": 1,
    "traffic": {"ping_loss_pct": 0.0, "bytes_in": 39274, "bytes_out": 39274, "billable_bytes": 78548},
    "session": {"allotment_msat": "39.274", "used_msat": "78.548", "state": "grace"},
    "pause_strict": "unsupported",
    "non_durable_cut": {
      "disconnect_cmd_ms": 49,
      "seller_down_ms": 764,
      "reconnect_mode": "auto",
      "reconnect_total_ms": 6616,
      "reconnect_after_down_ms": 5852,
      "link_id_after": 2,
      "ping_after_cut_ok": false,
      "ping_after_reconnect_ok": true
    },
    "durable_evict": {
      "mode": "deny+disconnect",
      "acl_wait_ms": 978,
      "cmd_ms": 1099,
      "seller_down_ms": 2142,
      "held_s": 3.0,
      "seller_link_present": false,
      "buyer_link_present": false,
      "readmit_mode": "auto",
      "link_readmit_ms": 1873,
      "total_readmit_ms": 2701,
      "link_id_after": 3,
      "ping_ok": true
    }
  }
}
```

## Measurements

| Metric | Run 1 (bare disconnect) | Run 2 (durable evict) |
|---|---|---|
| ACL allow effective | 613 ms | 925 ms |
| Link up after allow | 113 ms | 92 ms |
| Billable traffic | 70,274 B | 78,548 B |
| Disconnect command | 46 ms | 49 ms |
| Link down observed | 777 ms | 764 ms |
| Auto reconnect | **6,756 ms**, new `link_id=2` | **6,616 ms**, new `link_id=2` |
| In-band ping after cut | fail | fail |
| In-band ping after reconnect | pass, no payment | pass, no payment |
| Durable ACL wait | 812 ms (separate deny) | **978 ms** |
| Durable down observed | n/a (bare disconnect) | 2,142 ms |
| Hold after deny + disconnect | 3 s | 3 s, no link |
| Re-admit ACL | 819 ms | 829 ms |
| Re-admit link | 3,131 ms | 1,873 ms |
| **Total re-admit** | **3,950 ms** | **2,701 ms** |

## Repeatability (current code)

Three more runs after the durable-evict change. Each run starts from a fresh
compose project, so the ACL files and `link_id` start clean. All four current-code
runs (the main Run 2 plus these three) agree:

| Run | ACL allow | Bare down | Bare reconnect | Durable ACL wait | Durable down | Re-admit ACL | Re-admit link | **Total re-admit** | Held | link ids |
|---|---|---|---|---|---|---|---|---|---|---|
| Run 2 | 925 | 764 | 6,616 | 978 | 2,142 | 829 | 1,873 | **2,701** | 3 s | 1→2→3 |
| Rep 1 | 704 | 824 | 6,792 | 856 | 1,972 | 806 | 2,075 | **2,881** | 3 s | 1→2→3 |
| Rep 2 | 700 | 848 | 6,919 | 762 | 1,908 | 749 | 1,995 | **2,744** | 3 s | 1→2→3 |
| Rep 3 | 788 | 625 | 6,496 | 835 | 2,048 | 813 | 1,914 | **2,727** | 3 s | 1→2→3 |

| Metric | Range (n=4, current code) |
|---|---|
| ACL allow effective | 700–925 ms |
| Bare disconnect → down | 625–848 ms |
| Bare disconnect → auto reconnect | **6,496–6,919 ms** |
| Durable ACL wait | 762–978 ms |
| Durable evict → down | 1,908–2,142 ms |
| Re-admit ACL | 749–829 ms |
| Re-admit link | 1,873–2,075 ms |
| **Re-admit total** | **2,701–2,881 ms** |
| Durable hold | 3 s, no link, every run |
| `link_id` | 1→2 after bare cut, →3 after durable re-admit, every run |

Run 1 used the old bare-disconnect code and is excluded from the range; it is
kept above because it is the run that showed the cut was not durable.

## Interpretation

1. **A bare `disconnect` is not eviction.** With `connect_policy: auto_connect`
   the buyer re-established the link in **6.5–6.9 s**, with a fresh `link_id`
   and no new payment. The cut is a blip, not a gate. `evict` MUST deny the
   npub as well as disconnect.
2. **The in-band path dies during the cut.** Ping over the FIPS link fails
   immediately after disconnect and returns on reconnect. If payment rides the
   link (Ethernet, BLE, no IP fallback), the payment lane dies with it — and in
   this run it came back without payment. That is the free-ride window.
3. **Durable eviction is deny → wait → disconnect.** Deny is effective in
   ~0.8–1.0 s. Disconnecting before that leaves a window in which auto_connect
   can re-admit the peer. After the ACL is effective, the link stays down; a
   3 s hold showed no link on either side.
4. **Re-admission costs ACL latency plus a handshake.** **2.701–2.881 s** across four runs (0.75–0.83 s ACL + 1.87–2.08 s link).
   Run 1's explicit path was 3.95 s.
   That is the number P4 should quote for `evicted → paid`.
5. **`grace` is still unimplemented.** Strict pause raises. The crude fallback
   is now a durable eviction, which is correct for `evicted` but does not make
   `pause` possible. Patch (b) remains the load-bearing change.
6. **The sidecar changed because of this experiment.** `FipsGate.evict()` now
   denies, polls `fipsctl acl show` until the deny is effective, then
   disconnects. `pause()` in crude mode calls it. 32 unit tests pass.

## Caveats

- Five runs total, one topology. Run 1 used the old code; the range above is
  from the four current-code runs. Repeat on TCP and Ethernet before generalising.
- No mint and no payment. The "payment lane" is the in-band FIPS path; the
  Docker bridge is an out-of-band network but carries no payment service.
- The seller is passive and the buyer is the only dialer. A symmetric
  auto-connect topology would need both ACLs set, or the outbound side bypasses
  the seller's inbound gate.
- ICMP traffic, not a real application; the byte counts are for metering
  sanity, not a price.

## Follow-ups

- [x] Make `evict` durable: deny, wait for the ACL to be effective, then
      disconnect. Re-run this experiment (Run 2).
- [ ] Re-run 3–5 times and range the ACL/handshake numbers.
- [ ] Repeat with TCP and with Ethernet (no IP fallback).
- [ ] Add a test mint and show that re-admission requires a new payment.
- [x] Cite this result in `spec-drafts/04-pause-and-renewal.md`.

## Artefacts

- `harness/exp-c/docker-compose.yaml`
- `harness/exp-c/exp_c.py`
- `harness/exp-c/run-exp-c.sh`
- `harness/exp-c/configs/`
- containers left up for inspection at run time
