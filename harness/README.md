# Harness

The lab side of the experiments. This directory holds the topology, the helper
scripts, and the notes needed to reproduce a run. It does **not** hold secrets,
keys, or results — those go in `results/`.

## Status

Phase 0 scripts exist and work against the fleet. The lab topology (Ethernet
`veth` pair, local mint) is not built yet; it is Phase 1–3 work.

## Layout

```
harness/
├── scripts/
│   ├── gen-npub.py          # throwaway secp256k1 npub for ACL tests
│   ├── sample-counters.sh   # two samples of show transports/links, deltas
│   └── acl-latency.sh       # add/remove a throwaway npub, time the effect
├── ethernet-lab/
│   ├── Dockerfile           # alpine + iproute2 + nftables + python3
│   ├── frame-gate-test.py   # veth + nft netdev correctness test
│   └── run-frame-gate.sh    # build and run it
├── fips-lab/
│   └── README.md            # using upstream testing/static as a 2-node lab
├── exp-c/                    # two-node cut/re-admit lab
│   ├── docker-compose.yaml
│   ├── configs/              # test identities (not secrets)
│   ├── exp_c.py
│   ├── repeat.sh
│   └── run-exp-c.sh
├── pause/                    # patch (b) A-B-C transit-block test
│   ├── configs/
│   ├── control.py
│   ├── pause.py
│   └── run-pause.sh
├── demo/                     # Phase 1 pay/admit/exhaust/re-admit demo
│   ├── demo.py
│   └── run-demo.sh
├── mint/                     # Nutshell FakeWallet mint + offline verifier
│   ├── run-mint.sh
│   ├── mint-token.sh
│   ├── verify_token.py
│   └── verify-offline.sh
├── exp-h/                    # three-node re-parenting triangle
│   ├── docker-compose.yaml
│   ├── configs/
│   ├── exp_h.py
│   └── run-exp-h.sh
└── README.md
```

## Fleet access

Direct `ssh host-a` is unreliable: `host-a.fips` resolves but the path does not
respond. Use the jump host:

```sh
ssh -o BatchMode=yes c03rad0r@gateway.example \
  'ssh -o BatchMode=yes host-a "fipsctl show status"'
```

`sample-counters.sh` takes an optional third argument for the jump host:

```sh
harness/scripts/sample-counters.sh host-a 10 c03rad0r@gateway.example
```

Fleet inventory (2026-11-03):

| Host | FIPS | Transports |
|---|---|---|
| `gateway`, `host-c`, `host-a`, `host-d`, `host-e` | 0.5.3 (`f4a5b4a8e6`) | tcp, udp |
| `host-f`, `host-b` | 0.5.1 | tcp, udp |

**There is no Ethernet or BLE transport on any fleet node.** Exp E and the
Ethernet/BLE demos are lab-only until that changes.

`host-b` has passwordless sudo and is the ACL test host. Its ACL is
`deny_all=true`, `effective_mode=allow_then_deny_all`.

## Scripts

### `gen-npub.py`

Generates a valid bech32 `npub` from 32 random bytes. Nobody holds the private
key, so writing it to an ACL changes no real peer's access.

```sh
harness/scripts/gen-npub.py
# npub1...
```

Optional argument: 32 bytes of hex, for a deterministic test vector.

### `sample-counters.sh`

Samples `fipsctl show transports` and `fipsctl show links` twice, `SECS` apart,
and prints deltas, rates and mean frame size.

```sh
harness/scripts/sample-counters.sh host-a 10
```

It is read-only. The boundary note it prints is the point: counters are FMP
frame bytes at the transport API, excluding medium encapsulation.

### `acl-latency.sh`

Appends a throwaway npub to `/etc/fips/peers.allow` on the target, polls
`fipsctl acl show` until it appears in the **effective** allow set, restores the
file from a backup, and polls until it disappears. Three runs by default.

```sh
harness/scripts/acl-latency.sh host-b 3
```

It always restores the file. Check `restored_lines` in the output against the
original line count.

## `ethernet-lab/`

A container-based `veth` + `nft` lab, used for the frame-gate correctness test.

```sh
harness/ethernet-lab/run-frame-gate.sh 200
```

It needs Docker but not root on the host: the container gets `NET_ADMIN` and
`NET_RAW`, and no host network. It confirms that nft `netdev` ingress matches
EtherType `0x2121` and honours an `ether_addr` set.

**Do not count with AF_PACKET.** Packet taps run before the netdev ingress
hook, so a packet socket still sees frames nft dropped. Use nft counters for
`0x2121`, and a handled EtherType (IPv4/UDP) to prove real delivery. The first
version of the test made this mistake and reported a false pass.

Result: `results/E-nft-2026-11-03.md`.

It does **not** test `ndsctl`, real air time or throughput. A real AP is still
needed for the captive-portal half of Exp E.

## `fips-lab/`

Notes on using the upstream FIPS `testing/static` Docker lab as the two-node
pair for Exp C/H. It gives real `fipsd` processes and control sockets; it does
not give an Ethernet pair, a captive portal or a mint. See
`harness/fips-lab/README.md`.

## `pause/`

`harness/pause/` runs the patched-FIPS A–B–C chain and blocks A's transit at B
via `set_forwarding`, while checking A→B and the A–B link survive. Result:
`results/PB-2026-11-03-per-peer-forwarding.md`. `run-pay-demo.sh` adds real
offline ecash and the full unpaid → paid → pause → renew loop
(`results/PD-2026-11-03-pause-payment.md`).

## `demo/`

`harness/demo/` runs the Phase 1 story on the Exp C lab with the real Nutshell
mint: unpaid free ride, offline payment, exhaustion, durable eviction, prepaid
re-admission. Result: `results/DEMO-2026-11-03-buyer-exhausts.md`.

## `exp-c/` and `exp-h/`

Two working labs built on `fips-test:latest`:

- `exp-c` — two nodes, passive seller, durable eviction and re-admission.
  Results: `results/C-2026-11-03-cut-readmit.md`.
- `exp-h` — three-node triangle, ACL-deny of the current parent.
  Results: `results/H-2026-11-03-reparent.md`.

Both use `docker exec` to talk to the node's control socket and mount the
sidecar read-only. Run `harness/exp-c/repeat.sh 3` for a range.

## Planned lab topology

Phase 1–2 adds:

```
┌──────────────┐   veth / bridge   ┌──────────────┐
│ seller netns │◄─────────────────►│ buyer netns  │
│ fipsd        │                   │ fipsd        │
│ tollgate-fips│                   │ traffic-gen  │
│ control.sock │                   │              │
└──────┬───────┘                   └──────────────┘
       │
┌──────▼───────┐
│ local mint   │  test unit only, no mainnet
└──────────────┘
```

- `veth` pair for the Ethernet transport tests (EtherType `0x2121` is visible
  on the veth, so nft `netdev` can be exercised).
- A real AP is still required for the `ndsctl` half of Exp E.
- The mint is a local Cashu test mint; no mainnet funds.

## Rules

- Check `df -h` on any fleet node before writing.
- Record FIPS version and rev with every result.
- Restore any file you touch, and say so in the result.
- No mainnet funds.
