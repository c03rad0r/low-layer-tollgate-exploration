#!/usr/bin/env python3
"""Exp C: cut and re-admit on a two-node FIPS lab.

Run from the host, with the sidecar importable (PYTHONPATH=sidecar). Talks to
each node with `docker exec`, so the sidecar itself runs where it would run in
production: beside the seller's control socket.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import time
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.gate import FipsGate, PauseUnsupported
from tollgate_fips.meter import delta, format_msat, snapshot
from tollgate_fips.runner import DockerRunner, RunnerError
from tollgate_fips.session import Session

SELLER = "lt-exp-c-seller"
BUYER = "lt-exp-c-buyer"


def docker_exec(container: str, argv, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container, *argv],
        capture_output=True, text=True, timeout=timeout,
    )


def wait_for(predicate, timeout: float, interval: float = 0.05):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        value = predicate()
        if value:
            return time.monotonic() - started, value
        time.sleep(interval)
    return None, None


def peer_for(fips: Fipsctl, npub: str) -> Optional[Dict[str, Any]]:
    for peer in fips.peers():
        if peer.get("npub") == npub:
            return peer
    return None


def write_acl(container: str, allow_npub: Optional[str]) -> None:
    allow = f"{allow_npub}\n" if allow_npub else ""
    deny = "ALL\n"
    code = (
        "import pathlib; "
        "pathlib.Path('/etc/fips/peers.allow').write_text(%r); "
        "pathlib.Path('/etc/fips/peers.deny').write_text(%r)"
    ) % (allow, deny)
    result = docker_exec(container, ["python3", "-c", code])
    if result.returncode != 0:
        raise RuntimeError(f"ACL write failed: {result.stderr.strip()}")


def acl_show(container: str) -> Dict[str, Any]:
    result = docker_exec(container, ["fipsctl", "acl", "show"])
    if result.returncode != 0:
        raise RuntimeError(f"fipsctl acl show failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


class DockerAclStore:
    """FileAclStore for a node running in a container.

    The sidecar normally runs on the seller and writes the files directly. The
    host-side Exp C orchestrator has to reach them with `docker exec`.
    """

    def __init__(self, container: str):
        self.container = container

    def allow(self, npub: str) -> bool:
        write_acl(self.container, npub)
        return True

    def deny(self, npub: str) -> bool:
        write_acl(self.container, None)
        return True

    def allowed(self, npub: str) -> bool:
        return npub in acl_show(self.container).get("allow_entries", [])

    def denied(self, npub: str) -> bool:
        state = acl_show(self.container)
        return bool(state.get("deny_all")) or npub in state.get("deny_entries", [])

    def entries(self):
        state = acl_show(self.container)
        return state.get("allow_entries", []), state.get("deny_entries", [])


def acl_effective(container: str, npub: Optional[str]) -> bool:
    state = acl_show(container)
    if not state.get("deny_all"):
        return False
    if npub is None:
        return not state.get("allow_entries")
    return npub in state.get("allow_entries", [])


def measure_acl_write(container: str, allow_npub: Optional[str],
                      timeout: float = 5.0) -> Tuple[float, Dict[str, Any]]:
    write_acl(container, allow_npub)
    elapsed, state = wait_for(
        lambda: acl_show(container) if acl_effective(container, allow_npub) else None,
        timeout,
    )
    if elapsed is None:
        raise RuntimeError(f"ACL did not take effect within {timeout}s")
    return elapsed, state


def wait_link(seller: Fipsctl, buyer: Fipsctl, seller_npub: str,
              buyer_npub: str, timeout: float):
    def both():
        sp = peer_for(seller, buyer_npub)
        bp = peer_for(buyer, seller_npub)
        return (sp, bp) if sp and bp else None

    return wait_for(both, timeout)


def ping6(container: str, addr: str, count: int = 3, size: Optional[int] = None,
          interval: Optional[str] = None, timeout: int = 1) -> Dict[str, Any]:
    argv = ["ping6", "-c", str(count), "-W", str(timeout)]
    if size is not None:
        argv += ["-s", str(size)]
    if interval is not None:
        argv += ["-i", interval]
    argv.append(addr)
    result = docker_exec(container, argv, timeout=count * max(timeout, 1) + 15)
    loss = None
    match = re.search(r"(\d+(?:\.\d+)?)% packet loss", result.stdout)
    if match:
        loss = float(match.group(1))
    return {
        "ok": result.returncode == 0,
        "loss_pct": loss,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def main() -> int:
    global SELLER, BUYER
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", default="1000", help="bytes per millisat")
    parser.add_argument("--traffic-bytes", type=int, default=48_000,
                        help="payload bytes per ping burst (roughly)")
    parser.add_argument("--deny-hold", type=float, default=3.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--seller-container", default=SELLER)
    parser.add_argument("--buyer-container", default=BUYER)
    parser.add_argument("--label", default="udp", help="transport label for the summary")
    args = parser.parse_args()

    SELLER = args.seller_container
    BUYER = args.buyer_container

    seller = Fipsctl(DockerRunner(SELLER))
    buyer = Fipsctl(DockerRunner(BUYER))
    rate = Decimal(args.rate)

    # -- daemons and identity -------------------------------------------

    def running(fips: Fipsctl):
        try:
            status = fips.status()
        except RunnerError:
            return None
        return status if status.get("state") == "running" else None

    elapsed, _ = wait_for(lambda: running(seller), 20)
    if elapsed is None:
        raise RuntimeError("seller daemon did not come up")
    elapsed, _ = wait_for(lambda: running(buyer), 20)
    if elapsed is None:
        raise RuntimeError("buyer daemon did not come up")

    seller_status = seller.status()
    buyer_status = buyer.status()
    seller_npub = seller_status["npub"]
    buyer_npub = buyer_status["npub"]
    seller_addr = seller_status.get("ipv6_addr")
    print(f"seller npub={seller_npub} version={seller_status.get('version')} "
          f"addr={seller_addr}")
    print(f"buyer  npub={buyer_npub} version={buyer_status.get('version')}")

    # -- strict ACL, measured on 0.6.0-dev ------------------------------
    acl_initial_ms, acl_state = measure_acl_write(SELLER, buyer_npub)
    print(f"ACL allow {buyer_npub[:20]}... effective in {acl_initial_ms*1000:.0f} ms "
          f"(mode={acl_state.get('effective_mode')})")

    # -- bring the link up under the gate ------------------------------
    elapsed, pair = wait_link(seller, buyer, seller_npub, buyer_npub, 20)
    if pair is None:
        docker_exec(BUYER, ["fipsctl", "connect", seller_npub, "seller:2121", "udp"])
        elapsed, pair = wait_link(seller, buyer, seller_npub, buyer_npub, 15)
    if pair is None:
        print("FATAL: link did not come up", file=sys.stderr)
        return 2
    seller_peer, _ = pair
    link_id_before = seller_peer.get("link_id")
    print(f"link up: link_id={link_id_before} (waited {elapsed*1000:.0f} ms)")

    before_ping = ping6(BUYER, seller_addr)
    print(f"ping before: ok={before_ping['ok']} loss={before_ping['loss_pct']}%")

    # -- traffic, then meter it ----------------------------------------
    counters_before = snapshot(seller.peers(), seller.links())
    # ~48 KB of payload in 40 frames; replies come back too.
    traffic = ping6(BUYER, seller_addr, count=40, size=1200, interval="0.02")
    counters_after = snapshot(seller.peers(), seller.links())
    readings = delta(counters_before, counters_after, rate, "both")
    reading = next((r for r in readings if r.npub == buyer_npub), None)
    if reading is None or reading.billable_bytes == 0:
        print("FATAL: no billable bytes observed", file=sys.stderr)
        return 2
    print(f"traffic: ping loss={traffic['loss_pct']}% "
          f"metered in={reading.bytes_in} out={reading.bytes_out} "
          f"total={reading.billable_bytes} cost={format_msat(reading.cost_msat)} msat")

    # -- session exhausts, strict pause fails, crude pause disconnects --
    allotment = (Decimal(reading.billable_bytes) / rate) / 2
    session = Session(
        npub=buyer_npub,
        rate_bytes_per_msat=rate,
        allotment_msat=allotment,
        grace_seconds=30.0,
    )
    session.pay(allotment)
    session.charge(reading.billable_bytes)
    print(f"session: allotment={format_msat(allotment)} msat "
          f"used={format_msat(session.used_msat)} msat state={session.state.value} "
          f"forwarding={session.forwarding_allowed}")

    strict_error = None
    try:
        FipsGate(seller).pause(buyer_npub)
    except PauseUnsupported as exc:
        strict_error = str(exc).splitlines()[0]
        print(f"pause(strict): UNSUPPORTED — {strict_error}")

    store = DockerAclStore(SELLER)

    # -- cut 1: a bare disconnect is not eviction ------------------------
    cut_started = time.monotonic()
    seller.disconnect(buyer_npub)
    disconnect_cmd_ms = (time.monotonic() - cut_started) * 1000
    print(f"cut(non-durable): fipsctl disconnect returned in "
          f"{disconnect_cmd_ms:.0f} ms")

    down_seller, _ = wait_for(
        lambda: peer_for(seller, buyer_npub) is None, 5)
    down_buyer, _ = wait_for(
        lambda: peer_for(buyer, seller_npub) is None, 5)
    down_at = time.monotonic()
    seller_down_ms = (down_at - cut_started) * 1000
    print(f"link down: seller_observed={down_seller is not None} "
          f"buyer_observed={down_buyer is not None} at {seller_down_ms:.0f} ms")

    after_cut_ping = ping6(BUYER, seller_addr, count=2)

    elapsed, pair2 = wait_link(seller, buyer, seller_npub, buyer_npub, 20)
    reconnect_mode = "auto"
    reconnect_total_ms = (time.monotonic() - cut_started) * 1000
    if pair2 is None:
        reconnect_mode = "explicit"
        trigger = time.monotonic()
        docker_exec(BUYER, ["fipsctl", "connect", seller_npub, "seller:2121", "udp"])
        elapsed, pair2 = wait_link(seller, buyer, seller_npub, buyer_npub, 15)
        reconnect_total_ms = (trigger - cut_started) * 1000 + (elapsed or 0) * 1000
    if pair2 is None:
        print("FATAL: link did not reconnect after a bare disconnect", file=sys.stderr)
        return 2
    seller_peer2, _ = pair2
    link_id_after_auto = seller_peer2.get("link_id")
    reconnect_after_down_ms = (time.monotonic() - down_at) * 1000
    after_reconnect_ping = ping6(BUYER, seller_addr, count=2)
    print(f"link back WITHOUT payment: mode={reconnect_mode} "
          f"link_id={link_id_after_auto} total={reconnect_total_ms:.0f} ms "
          f"after_down={reconnect_after_down_ms:.0f} ms")

    # -- cut 2: durable eviction = deny, wait for ACL, disconnect -------
    gate = FipsGate(seller, acl=store, allow_disconnect=True)
    durable_started = time.monotonic()
    crude = gate.pause(buyer_npub)
    durable_cmd_ms = (time.monotonic() - durable_started) * 1000
    print(f"pause(crude/durable): mode={crude.mode} "
          f"acl_wait={crude.acl_wait_ms} ms cmd={durable_cmd_ms:.0f} ms")
    print(f"  warning: {crude.warning}")

    down_seller2, _ = wait_for(
        lambda: peer_for(seller, buyer_npub) is None, 5)
    down_buyer2, _ = wait_for(
        lambda: peer_for(buyer, seller_npub) is None, 5)
    durable_down_at = time.monotonic()
    durable_down_ms = (durable_down_at - durable_started) * 1000
    print(f"durable link down: seller_observed={down_seller2 is not None} "
          f"buyer_observed={down_buyer2 is not None} at {durable_down_ms:.0f} ms")

    time.sleep(args.deny_hold)
    seller_has = peer_for(seller, buyer_npub) is not None
    buyer_has = peer_for(buyer, seller_npub) is not None
    print(f"deny held for {args.deny_hold:.1f}s: seller_link={seller_has} "
          f"buyer_link={buyer_has}")

    # -- re-admit --------------------------------------------------------
    acl_allow_ms, _ = measure_acl_write(SELLER, buyer_npub)
    readmit_started = time.monotonic()
    elapsed, pair3 = wait_link(seller, buyer, seller_npub, buyer_npub, 3)
    readmit_mode = "auto"
    link_readmit_ms = (time.monotonic() - readmit_started) * 1000
    if pair3 is None:
        readmit_mode = "explicit"
        trigger = time.monotonic()
        docker_exec(BUYER, ["fipsctl", "connect", seller_npub, "seller:2121", "udp"])
        elapsed, pair3 = wait_link(seller, buyer, seller_npub, buyer_npub, 15)
        link_readmit_ms = (trigger - readmit_started) * 1000 + (elapsed or 0) * 1000
    if pair3 is None:
        print("FATAL: link did not re-admit", file=sys.stderr)
        return 2
    seller_peer3, _ = pair3
    link_id_after_durable = seller_peer3.get("link_id")
    after_readmit_ping = ping6(BUYER, seller_addr, count=2)
    print(f"ACL allow: effective in {acl_allow_ms*1000:.0f} ms; "
          f"link re-admitted mode={readmit_mode} in {link_readmit_ms:.0f} ms "
          f"(total {(acl_allow_ms*1000 + link_readmit_ms):.0f} ms) "
          f"link_id={link_id_after_durable}")

    summary = {
        "date": datetime.date.today().isoformat(),
        "fips_version": seller_status.get("version"),
        "transport": args.label,
        "seller_npub": seller_npub,
        "buyer_npub": buyer_npub,
        "acl": {
            "initial_allow_ms": round(acl_initial_ms * 1000),
            "allow_readmit_ms": round(acl_allow_ms * 1000),
        },
        "exp_c": {
            "link_id_before": link_id_before,
            "traffic": {
                "ping_loss_pct": traffic["loss_pct"],
                "bytes_in": reading.bytes_in,
                "bytes_out": reading.bytes_out,
                "billable_bytes": reading.billable_bytes,
            },
            "session": {
                "allotment_msat": str(allotment),
                "used_msat": str(session.used_msat),
                "state": session.state.value,
            },
            "pause_strict": "unsupported",
            "pause_strict_error": strict_error,
            "non_durable_cut": {
                "disconnect_cmd_ms": round(disconnect_cmd_ms),
                "seller_down_ms": round(seller_down_ms),
                "reconnect_mode": reconnect_mode,
                "reconnect_total_ms": round(reconnect_total_ms),
                "reconnect_after_down_ms": round(reconnect_after_down_ms),
                "link_id_after": link_id_after_auto,
                "ping_after_cut_ok": after_cut_ping["ok"],
                "ping_after_reconnect_ok": after_reconnect_ping["ok"],
            },
            "durable_evict": {
                "mode": crude.mode,
                "acl_wait_ms": crude.acl_wait_ms,
                "cmd_ms": round(durable_cmd_ms),
                "seller_down_ms": round(durable_down_ms),
                "held_s": args.deny_hold,
                "seller_link_present": seller_has,
                "buyer_link_present": buyer_has,
                "readmit_mode": readmit_mode,
                "link_readmit_ms": round(link_readmit_ms),
                "total_readmit_ms": round(acl_allow_ms * 1000 + link_readmit_ms),
                "link_id_after": link_id_after_durable,
                "ping_ok": after_readmit_ping["ok"],
            },
        },
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
