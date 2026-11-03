# FIPS lab (upstream `testing/static`)

The FIPS repo ships a multi-node Docker lab. We did not write it and we do not
modify it. This directory records how to use it as the two-node lab that Exp C
and the transport demos need.

Pinned tree for the notes: `2ba790b` (`0.6.0-dev`, 2026-11-02). The fleet is
0.5.3, so record both when comparing.

## What it gives us

- Real `fipsd` processes with TUN devices, control sockets, peer links, the
  spanning tree and multi-hop routing.
- UDP by default, with TCP available; five nodes in `mesh` and `chain`
  topologies.
- Deterministic identities and generated configs.
- `ping-test.sh` / `iperf-test.sh` for reachability and throughput.

That is enough for Exp C (cut and re-admit) and Exp H (ACL-deny re-parenting)
once the sidecar is wired in.

It does **not** give us:

- an Ethernet transport pair (the static lab peers over UDP);
- a captive portal or `ndsctl`;
- a mint, payments or a spent journal;
- our sidecar. The sidecar has to be added as a container or run on a node.

## Quick start (upstream instructions, condensed)

From the FIPS repo root:

```bash
./testing/scripts/build.sh
./testing/static/scripts/generate-configs.sh mesh
docker compose -f testing/static/docker-compose.yml up -d
./testing/static/scripts/ping-test.sh mesh
docker compose -f testing/static/docker-compose.yml down
```

Use `--profile chain` for a linear A–B–C–D–E topology. Check the upstream
`testing/static/README.md` for the current command shape; it changes.

## How to add the sidecar

The gate needs three things from a node:

1. the control socket (`fipsctl show ...`, `fipsctl disconnect`);
2. `/etc/fips/peers.allow` and `/etc/fips/peers.deny`;
3. a way to run `tollgate_fips` with those mounted.

Options, cheapest first:

- **Sidecar in the node container.** Add a second process to the node's
  container that mounts the same `/run/fips` and `/etc/fips`. No network
  change; the control socket is local.
- **Sidecar as a sibling container.** Share the control socket and ACL files
  as volumes. The socket path is inside the node's filesystem, so this needs a
  shared volume or a `docker exec` runner.
- **Sidecar over SSH.** Works for metering, but ACL writes need sudo and are
  not the shape we want in a demo.

The first option is the one to implement.

## Ethernet pair

The upstream lab does not have an Ethernet topology. Build one on top of
`harness/ethernet-lab/`:

1. two network namespaces (or containers) joined by a `veth` pair;
2. `fipsd` with `transports.ethernet` on each side;
3. the `netdev` gate from `harness/ethernet-lab/` in the receiver namespace;
4. the sidecar on the seller, admitting by npub and updating the MAC set on
   `paid` / `evicted`.

That is the Phase 2 `experiments/03-ethernet/` target, and it is also where the
`ndsctl` question can finally be answered with a real AP.

## Rules

- Do not modify the upstream tree for our experiments. Copy configs into this
  repo if they need to change.
- Pin the FIPS commit in every result file.
- No mainnet funds.
- The frame gate is rate control, not authorisation. Do not describe it
  otherwise in a PR.
