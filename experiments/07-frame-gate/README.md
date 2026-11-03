# 07 — Frame gate

**Question:** can an nft `netdev` chain drop EtherType `0x2121` from
unauthorised MACs at line rate, and is that authorisation or only rate control?

**Status:** partial. The nft rule/set correctness test passes on `veth`
(`../../results/E-nft-2026-11-03.md`). Throughput (E2/E4) and the real-AP cases
(E/E3) are not started.

## Topology

```
AP / bridge ── authorised station (seller, paid)
            └─ unauthorised station (no session)
```

One `netdev` ingress chain per interface, an `authorised_macs` set, and a
traffic generator on the unauthorised station.

## What is being tested

1. **E2 — drop cost.** Token bucket at 1k / 10k / 100k pps. Measure CPU and
   achieved drop rate against a userspace alternative.
2. **E3 — association-only bypass.** Associate to an open/802.11s SSID without
   paying. Do `0x2121` frames cross? (This is the same question as Exp E, from
   the Wi-Fi side.)
3. **E4 — nft vs tc/eBPF.** Same pps ramp, compare ceiling and CPU.
4. **Correctness.** The set is populated on `paid` and removed on `evicted`.
   A stale MAC must not keep access.

## Harness

```sh
harness/ethernet-lab/run-frame-gate.sh 200
```

Builds the `veth` pair and runs the set-semantics test. Use nft counters for
the `0x2121` verdict; **AF_PACKET taps run before the ingress hook** and will
report a false pass.

## nft sketch

```
table netdev tollgate {
  set authorised_macs { type ether_addr; }
  chain ingress {
    type filter hook ingress device "eth0" priority 0;
    ether type 0x2121 ether saddr @authorised_macs accept
    ether type 0x2121 drop
  }
}
```

Add a `limit rate` clause per MAC for the rate-control half.

## Pass criteria

- [ ] Unauthorised MACs cannot put `0x2121` frames on the link at line rate.
- [ ] Drop cost is recorded at all three pps levels.
- [ ] The result file states plainly: **this is rate/abuse control, not
      authorisation; MACs are spoofable.**
- [ ] Set updates track the session state machine.

## Reporting rule

Do not describe this gate as "authorising" a client. The authorisation is the FMP
link gate keyed on the npub. This distinction is the whole point of
`docs/0006-frame-gate.md`.
