"""Command-line entry point for the Phase 1 sidecar.

Read-only against a live node by default. ACL writes require `--yes`, and
`pause` fails loudly on FIPS 0.5.x/0.6.x because the forwarding hook is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal

from .control import UnixControl
from .fipsctl import Fipsctl
from .gate import AclError, FipsGate, FileAclStore, PauseUnsupported
from .meter import delta, format_msat
from .runner import LocalRunner, RunnerError, SSHRunner
from .session import Session, State


def _fipsctl(args) -> Fipsctl:
    runner = SSHRunner(args.host) if args.host else LocalRunner()
    return Fipsctl(runner)


def _cmd_status(args) -> int:
    status = _fipsctl(args).status()
    keep = ("npub", "version", "state", "link_count", "peer_count",
            "transport_count", "is_leaf_only")
    print(json.dumps({key: status.get(key) for key in keep}, indent=2))
    return 0


def _cmd_meter(args) -> int:
    fips = _fipsctl(args)
    rate = Decimal(args.rate)
    before = fips.peers(), fips.links()
    from .meter import snapshot
    prev = snapshot(*before)
    time.sleep(args.seconds)
    cur = snapshot(fips.peers(), fips.links())
    readings = delta(prev, cur, rate, args.direction)

    if args.json:
        print(json.dumps([
            {
                "npub": r.npub,
                "link_ids": list(r.link_ids),
                "bytes_in": r.bytes_in,
                "bytes_out": r.bytes_out,
                "billable_bytes": r.billable_bytes,
                "cost_msat": str(r.cost_msat),
                "label": r.label,
            }
            for r in readings
        ], indent=2))
        return 0

    print(f"window={args.seconds:.1f}s direction={args.direction} "
          f"rate={rate} B/msat label=all_frames")
    print(f"{'npub':64s} {'in':>10s} {'out':>10s} {'billable':>12s} {'msat':>12s}")
    for r in readings:
        print(f"{r.npub:64s} {r.bytes_in:10d} {r.bytes_out:10d} "
              f"{r.billable_bytes:12d} {format_msat(r.cost_msat):>12s}")
    print("\nBoundary: FMP frame bytes at the transport API, excluding medium "
          "encapsulation; control frames included (all_frames).")
    return 0


def _cmd_simulate(args) -> int:
    session = Session(
        npub=args.peer or "npub1sim",
        rate_bytes_per_msat=Decimal(args.rate),
        allotment_msat=Decimal(args.allotment_msat),
        grace_seconds=args.grace,
    )
    now = 0.0
    print(f"session={session.session_id} rate={args.rate} B/msat "
          f"allotment={args.allotment_msat} msat")
    print(f"{'t':>6s}  {'state':9s} event")
    print(f"{now:6.0f}  {session.state.value:9s} created")

    session.pay(Decimal(args.allotment_msat), now=now)
    print(f"{now:6.0f}  {session.state.value:9s} paid {args.allotment_msat} msat")

    cost = session.charge(args.bytes, now=now)
    print(f"{now:6.0f}  {session.state.value:9s} charged {args.bytes} B = "
          f"{format_msat(cost)} msat, remaining={format_msat(session.remaining_msat)}")
    session.tick(now=now)
    print(f"{now:6.0f}  {session.state.value:9s} tick")

    if session.state is State.GRACE:
        session.pay(Decimal(args.top_up_msat), now=now)
        print(f"{now:6.0f}  {session.state.value:9s} renewed "
              f"{args.top_up_msat} msat")
        session.charge(args.bytes, now=now)
        print(f"{now:6.0f}  {session.state.value:9s} charged again")
        session.tick(now=now)
        print(f"{now:6.0f}  {session.state.value:9s} tick")

    if session.state is State.GRACE:
        session.tick(now=now + args.grace + 1)
        print(f"{now + args.grace + 1:6.0f}  {session.state.value:9s} "
              f"grace expired ({session.evicted_reason})")

    print(f"\nforwarding_allowed={session.forwarding_allowed} "
          f"payment_lane_open={session.payment_lane_open} "
          f"link_open={session.link_open}")
    return 0


def _cmd_pause_check(args) -> int:
    control = (UnixControl(args.control_socket)
               if args.control_socket else None)
    gate = FipsGate(
        fipsctl=_fipsctl(args),
        allow_disconnect=args.allow_disconnect,
        control=control,
    )
    try:
        result = gate.pause(args.peer)
    except PauseUnsupported as exc:
        print("PAUSE UNSUPPORTED")
        print(exc)
        return 1
    print(json.dumps(result.__dict__, indent=2))
    return 0


def _cmd_acl(args) -> int:
    store = FileAclStore(args.allow_file, args.deny_file)
    if not args.yes:
        print(f"would {'allow' if args.action == 'admit' else 'deny'} "
              f"{args.peer} via {store.allow_path if args.action == 'admit' else store.deny_path}")
        print("re-run with --yes to write")
        return 0
    control = (UnixControl(args.control_socket)
               if getattr(args, "control_socket", None) else None)
    gate = FipsGate(acl=store, control=control)
    changed = gate.admit(args.peer) if args.action == "admit" else gate.deny(args.peer)
    print(f"{'changed' if changed else 'already present'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tollgate-fips")
    parser.add_argument("--host", help="inspect a remote node over ssh (read-only)")
    parser.add_argument("--rate", default="1000000",
                        help="bytes per millisat (default: 1000000)")
    parser.add_argument("--allow-file", default="/etc/fips/peers.allow")
    parser.add_argument("--deny-file", default="/etc/fips/peers.deny")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="node identity and counts")
    status.set_defaults(func=_cmd_status)

    meter = sub.add_parser("meter", help="sample per-peer counters and price them")
    meter.add_argument("--seconds", type=float, default=5.0)
    meter.add_argument("--direction", choices=("both", "in", "out"), default="both")
    meter.add_argument("--json", action="store_true")
    meter.set_defaults(func=_cmd_meter)

    sim = sub.add_parser("simulate", help="run the four-state machine offline")
    sim.add_argument("--peer", default="npub1sim")
    sim.add_argument("--allotment-msat", default="1000")
    sim.add_argument("--top-up-msat", default="1000")
    sim.add_argument("--bytes", type=int, default=2_000_000)
    sim.add_argument("--grace", type=float, default=30.0)
    sim.set_defaults(func=_cmd_simulate)

    pause = sub.add_parser("pause-check",
                           help="show that FIPS cannot pause one peer's forwarding")
    pause.add_argument("--peer", required=True)
    pause.add_argument("--allow-disconnect", action="store_true",
                       help="degrade pause to disconnect (destructive)")
    pause.add_argument("--control-socket", default=None,
                       help="send set_forwarding to this FIPS control socket")
    pause.set_defaults(func=_cmd_pause_check)

    adm = sub.add_parser("admit", help="append an npub to peers.allow")
    adm.add_argument("peer")
    adm.add_argument("--yes", action="store_true")
    adm.add_argument("--control-socket", default=None,
                     help="also set the runtime override at this socket")
    adm.set_defaults(func=_cmd_acl, action="admit")

    deny = sub.add_parser("deny", help="append an npub to peers.deny")
    deny.add_argument("peer")
    deny.add_argument("--yes", action="store_true")
    deny.add_argument("--control-socket", default=None,
                      help="also set the runtime override at this socket")
    deny.set_defaults(func=_cmd_acl, action="deny")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RunnerError, AclError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
