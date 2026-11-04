# Ethernet lab

A container-based `veth` + `nft` lab. It is enough to test the **frame-gate rule
and MAC-set semantics**, and to bring up an Ethernet FMP pair once a `fipsd`
binary is available. It is **not** enough to test `ndsctl` or real air time.

## Frame-gate correctness test

```sh
harness/ethernet-lab/run-frame-gate.sh 200
```

Builds `alpine:3.20` with `iproute2`, `nftables` and `python3`, then runs
`frame-gate-test.py` in a container with `NET_ADMIN` + `NET_RAW` and no host
network.

The test creates a `veth` pair, installs a `netdev` ingress chain on the receive
side, and checks:

1. IPv4/UDP is delivered with no table (baseline);
2. `ether type 0x0800 drop` blocks delivery — the control that proves the hook
   is on the real receive path;
3. a `0x2121` gate does not affect IPv4/UDP;
4. empty MAC set: `0x2121` dropped;
5. sender MAC added: `0x2121` accepted;
6. sender MAC removed: `0x2121` dropped;
7. unauthorised source MAC: `0x2121` dropped.

### The AF_PACKET trap

**Do not count frames with an AF_PACKET socket to test an ingress drop.**
Packet taps run before the `netdev` ingress hook, so an `AF_PACKET` reader sees
frames that nft has already dropped. The first version of this test did exactly
that and reported a false pass: nft's counter showed 200 dropped, the packet
socket still showed 200 received.

Use nft counters for the `0x2121` verdict. Use a handled EtherType (IPv4/UDP)
when you need to observe real delivery.

## What this does not answer

- **`ndsctl` / captive portal.** A real AP and a real portal are required. Veth
  cannot answer whether deauthorising a client stops `0x2121`.
- **Throughput / drop cost.** This is a correctness test. Exp E2 needs a pps
  ramp and CPU measurement.
- **Real air time and MAC rotation.** Ethernet and BLE radio behaviour is not
  modelled.
- **Authorisation.** MAC addresses are spoofable. This gate is rate and abuse
  control. Authorisation is the FMP link gate keyed on the npub.

## Using this for a FIPS Ethernet pair

The container has `NET_ADMIN`, so a future script can:

1. create two network namespaces and a `veth` pair;
2. run `fipsd` with the Ethernet transport in each namespace;
3. install the `netdev` gate in the receiver namespace;
4. wire the MAC set to the session state machine.

`fipsd` is not built here yet. See `patches/README.md` and the Phase 2 plan.

## Result

`results/E-nft-2026-11-03.md`

## Throughput (E2)

```sh
harness/ethernet-lab/run-throughput.sh            # 1k,10k,100k x 2 s
harness/ethernet-lab/run-throughput.sh 1000,10000,100000 2
```

Builds `low-layer-tollgate-frame-bench` (Alpine + gcc), creates a veth pair, and
compares nft drop/accept with a C userspace receiver. Result:
`results/E2-2026-11-03-frame-gate-throughput.md`.

## Per-MAC token bucket (E4)

```sh
harness/ethernet-lab/run-token-bucket.sh        # 3 repeats, 4 modes
harness/ethernet-lab/run-token-bucket.sh 1
```

Builds `low-layer-tollgate-token-bucket` (Alpine + clang + libbpf) and runs
`token-bucket-test.py`. Three senders (500 / 5,000 / 5,000 pps) cross a bridge;
the receiver counts survivors per source MAC. Modes: no gate, nft dynamic set,
tc `police` per MAC, and a tc/BPF classifier with an LRU map. Result:
`results/E4-2026-11-03-per-mac-token-bucket.md`.

The container needs `CAP_BPF`, `CAP_PERFMON` and `CAP_SYS_ADMIN` for the BPF
mode on this host (`kernel.unprivileged_bpf_disabled=2`); the nft and tc modes
only need `NET_ADMIN`.

## FrameGate module demo

```sh
harness/ethernet-lab/run-frame-gate-demo.sh
```

Runs `sidecar/tollgate_fips/frame_gate.py` against real nftables inside the E4
image: per-MAC rate limit with three senders, then an explicit block/unblock,
then the `default_deny` allow-list. Result:
`results/FRAMEGATE-2026-11-03-module.md`.

Note that the nft dynamic set creates a bucket element for every sender on its
first frame, including under-rate senders; presence means "seen", not "over the
limit".
