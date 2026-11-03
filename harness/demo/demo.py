#!/usr/bin/env python3
"""Phase 1 demo: the unpaid free ride, then pay -> exhaust -> cut -> re-admit.

Two-node FIPS lab, real Nutshell ecash, no real funds.

The first half is the failure the whole design exists for: with the link up and
the session `unpaid`, FIPS forwards traffic anyway. There is no per-peer
forwarding role, so the seller cannot block one peer while keeping the link.

The second half is the crude workaround: a real offline P2PK+DLEQ payment, a
durable eviction (deny + wait for ACL + disconnect), then a prepaid renewal and
re-admission. Payment is out-of-band (Docker/mint, not over FMP); the demo is
about admission and exhaustion.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))

import exp_c  # noqa: E402

from tollgate_fips.fipsctl import Fipsctl  # noqa: E402
from tollgate_fips.gate import FipsGate  # noqa: E402
from tollgate_fips.meter import delta, snapshot  # noqa: E402
from tollgate_fips.runner import DockerRunner, RunnerError  # noqa: E402
from tollgate_fips.session import Session, State  # noqa: E402

SELLER = "lt-exp-c-seller"
BUYER = "lt-exp-c-buyer"
SELLER_PUBKEY = "REPLACE_WITH_HEX_SEEDa4"
MINT_URL = "http://lt-mint:3338"
WORK = Path(os.environ.get("DEMO_WORK", "/tmp/opencode/demo-pay"))
IMAGE = "cashubtc/nutshell:latest"


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def mint_token(amount: int, name: str) -> Path:
    out = WORK / name
    run([str(ROOT / "harness/mint/mint-token.sh"), str(amount),
         SELLER_PUBKEY, str(out)], capture_output=True)
    if not out.exists():
        raise RuntimeError(f"mint-token.sh did not write {out}")
    return out


def cache_keys(token: Path, keys: Path) -> None:
    run([
        "docker", "run", "--rm", "--network", "lt-mint-net",
        "-e", "PYTHONPATH=/app",
        "-v", f"{WORK}:/data",
        "-v", f"{ROOT / 'harness/mint'}:/mint:ro",
        IMAGE, "python3", "/mint/verify_token.py", f"/data/{token.name}",
        "--keys-file", f"/data/{keys.name}",
        "--seller-pubkey", SELLER_PUBKEY, "--mint", MINT_URL,
    ], capture_output=True)


def gate_token(token: Path, keys: Path, db: str, buyer_npub: str,
               seller_npub: str) -> dict:
    result = subprocess.run([
        "docker", "run", "--rm",
        "-e", "PYTHONPATH=/app:/sidecar:/mint",
        "-v", f"{WORK}:/data",
        "-v", f"{ROOT / 'sidecar'}:/sidecar:ro",
        "-v", f"{ROOT / 'harness/mint'}:/mint:ro",
        IMAGE, "python3", "/mint/gate_token.py", f"/data/{token.name}",
        "--keys-file", f"/data/{keys.name}",
        "--seller-pubkey", SELLER_PUBKEY,
        "--seller-npub", seller_npub,
        "--buyer-npub", buyer_npub,
        "--mint", MINT_URL,
        "--db-dir", f"/data/{db}",
    ], capture_output=True, text=True)
    text = result.stdout
    try:
        summary = json.loads(text)
    except json.JSONDecodeError:
        try:
            start = text.rindex("\n{\n")
            summary = json.loads(text[start:])
        except (ValueError, json.JSONDecodeError):
            print(result.stdout[-3000:], file=sys.stderr)
            print(result.stderr[-3000:], file=sys.stderr)
            raise RuntimeError(f"gate_token.py failed (rc={result.returncode})")
    if result.returncode != 0 or not summary.get("verify_ok"):
        print(json.dumps(summary, indent=2), file=sys.stderr)
        raise RuntimeError("token did not verify/accept")
    return summary


def mint_stop() -> None:
    subprocess.run(["docker", "stop", "lt-mint"], capture_output=True)


def mint_start() -> None:
    subprocess.run(["docker", "start", "lt-mint"], capture_output=True)
    for _ in range(20):
        if subprocess.run(["curl", "-fsS", "http://127.0.0.1:3338/v1/info"],
                          capture_output=True).returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("mint did not restart")


def traffic(seller: Fipsctl, buyer_npub: str, seller_addr: str,
            rate: Decimal, count: int = 1):
    before = snapshot(seller.peers(), seller.links())
    exp_c.ping6(BUYER, seller_addr, count=count, size=1200, interval="0.02")
    time.sleep(0.05)
    after = snapshot(seller.peers(), seller.links())
    readings = delta(before, after, rate, "both")
    return next((r for r in readings if r.npub == buyer_npub), None)


def wait_ping(seller_addr: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = exp_c.ping6(BUYER, seller_addr, count=1)
        if last["ok"]:
            return last
        time.sleep(0.5)
    return last


def admit_after_acl(seller: Fipsctl, buyer: Fipsctl, seller_npub: str,
                    buyer_npub: str, timeout: float = 2.0):
    auto_ms, pair = exp_c.wait_link(seller, buyer, seller_npub, buyer_npub, timeout)
    if pair is not None:
        return "auto", auto_ms * 1000, pair
    trigger = time.monotonic()
    try:
        buyer.disconnect(seller_npub)
    except RunnerError:
        pass
    time.sleep(0.1)
    exp_c.docker_exec(BUYER, ["fipsctl", "connect", seller_npub,
                              "seller:2121", "udp"])
    _, pair = exp_c.wait_link(seller, buyer, seller_npub, buyer_npub, 10)
    return "explicit", (time.monotonic() - trigger) * 1000, pair


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    run([str(ROOT / "harness/mint/run-mint.sh")], capture_output=True)
    run(["docker", "compose", "-f", str(ROOT / "harness/exp-c/docker-compose.yaml"),
         "up", "-d", "--remove-orphans"], capture_output=True)

    seller = Fipsctl(DockerRunner(SELLER))
    buyer = Fipsctl(DockerRunner(BUYER))
    for name, client in (("seller", seller), ("buyer", buyer)):
        if exp_c.wait_for(lambda c=client: exp_c.running(c), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")
    seller_status = seller.status()
    buyer_status = buyer.status()
    seller_npub = seller_status["npub"]
    buyer_npub = buyer_status["npub"]
    seller_addr = seller_status["ipv6_addr"]

    # The lab starts with the link up and the session unpaid.
    _, pair = exp_c.wait_link(seller, buyer, seller_npub, buyer_npub, 20)
    if pair is None:
        raise RuntimeError("initial link did not form")
    link_id_initial = pair[0].get("link_id")
    session = Session(npub=buyer_npub, rate_bytes_per_msat=Decimal("1"),
                      allotment_msat=Decimal(0), grace_seconds=30.0)
    time.sleep(1.0)
    wait_ping(seller_addr)
    unpaid = None
    for _ in range(10):
        unpaid = traffic(seller, buyer_npub, seller_addr, Decimal("1"), count=5)
        if unpaid and unpaid.billable_bytes > 0:
            break
        time.sleep(0.2)
    unpaid_ping = wait_ping(seller_addr)
    unpaid_bytes = unpaid.billable_bytes if unpaid else 0
    unpaid_charged = session.charge(unpaid_bytes)
    print(f"unpaid: ping={unpaid_ping['ok']} bytes={unpaid_bytes} "
          f"charged={unpaid_charged} state={session.state.value}")

    # Payment 1: real token, verified offline, accepted by the gate.
    token1 = mint_token(50, "token1.txt")
    keys = WORK / "keys.json"
    cache_keys(token1, keys)
    mint_stop()
    gate1 = gate_token(token1, keys, f"gate1-{int(time.time())}",
                       buyer_npub, seller_npub)
    mint_start()
    token_msat = Decimal(gate1["amount"]) * 1000
    session.pay(token_msat)
    print(f"payment 1: offline={gate1['offline']} accepted={gate1['accepted']} "
          f"amount={gate1['amount']} sat state={session.state.value}")

    # Payment 2 is prepaid before exhaustion so re-admission does not wait for
    # a mint round trip. It is a second real token, verified offline.
    token2 = mint_token(50, "token2.txt")
    cache_keys(token2, keys)
    mint_stop()
    gate2 = gate_token(token2, keys, f"gate2-{int(time.time())}",
                       buyer_npub, seller_npub)
    mint_start()
    print(f"payment 2 (prepaid): offline={gate2['offline']} "
          f"accepted={gate2['accepted']} amount={gate2['amount']} sat")

    # Exhaust with per-packet metering, so the overshoot is one packet.
    wait_ping(seller_addr)
    total_bytes = 0
    pings = 0
    zero_streak = 0
    while session.state is State.PAID:
        reading = traffic(seller, buyer_npub, seller_addr, Decimal("1"), count=1)
        if reading is None or reading.billable_bytes == 0:
            zero_streak += 1
            if zero_streak > 10:
                raise RuntimeError("no metered bytes after 10 retries")
            continue
        zero_streak = 0
        total_bytes += reading.billable_bytes
        session.charge(reading.billable_bytes)
        pings += 1
        if pings > 80:
            raise RuntimeError("session did not exhaust in 80 pings")
    print(f"session: bytes={total_bytes} used={session.used_msat} msat "
          f"state={session.state.value} pings={pings}")

    # Durable eviction.
    gate = FipsGate(seller, acl=exp_c.DockerAclStore(SELLER),
                    allow_disconnect=True)
    cut_started = time.monotonic()
    paused = gate.pause(buyer_npub)
    cut_ms = (time.monotonic() - cut_started) * 1000
    exp_c.wait_for(lambda: exp_c.peer_for(seller, buyer_npub) is None, 5)
    exp_c.wait_for(lambda: exp_c.peer_for(buyer, seller_npub) is None, 5)
    after_cut_ping = exp_c.ping6(BUYER, seller_addr, count=2)
    print(f"evict: mode={paused.mode} cut={cut_ms:.0f} ms "
          f"ping={after_cut_ping['ok']}")

    # Re-admit against the prepaid token. The payment was already accepted, so
    # only the ACL and handshake are on the critical path.
    acl_ms = exp_c.measure_acl_write(SELLER, buyer_npub)[0]
    readmit_mode, link2_ms, pair2 = admit_after_acl(
        seller, buyer, seller_npub, buyer_npub)
    if pair2 is None:
        raise RuntimeError("no link after prepaid renewal")
    link_id_readmit = pair2[0].get("link_id")
    session2 = Session(npub=buyer_npub, rate_bytes_per_msat=Decimal("1"),
                       allotment_msat=Decimal(0), grace_seconds=30.0)
    session2.pay(Decimal(gate2["amount"]) * 1000)
    after_readmit_ping = exp_c.ping6(BUYER, seller_addr, count=2)
    print(f"re-admitted: acl={acl_ms*1000:.0f} ms mode={readmit_mode} "
          f"link={link2_ms:.0f} ms id={link_id_readmit} "
          f"ping={after_readmit_ping['ok']} state={session2.state.value}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": seller_status.get("version"),
        "seller_npub": seller_npub,
        "buyer_npub": buyer_npub,
        "link_id_initial": link_id_initial,
        "unpaid": {
            "ping": unpaid_ping["ok"],
            "billable_bytes": unpaid_bytes,
            "charged_msat": str(unpaid_charged),
            "state": State.UNPAID.value,
            "note": "FIPS forwarded while unpaid; no pause hook",
        },
        "payment_1": {k: gate1[k] for k in
                      ("offline", "accepted", "amount", "replay_before_settle",
                       "replay_after_settle")},
        "payment_2_prepaid": {k: gate2[k] for k in
                              ("offline", "accepted", "amount",
                               "replay_before_settle", "replay_after_settle")},
        "session": {"allotment_msat": str(token_msat),
                    "billable_bytes": total_bytes,
                    "used_msat": str(session.used_msat),
                    "overshoot_msat": str(session.used_msat - token_msat),
                    "pings": pings,
                    "state": session.state.value},
        "evict": {"mode": paused.mode, "acl_wait_ms": paused.acl_wait_ms,
                  "cut_ms": round(cut_ms), "ping_after": after_cut_ping["ok"]},
        "readmit": {"acl_ms": round(acl_ms * 1000), "mode": readmit_mode,
                    "link_ms": round(link2_ms), "link_id": link_id_readmit,
                    "ping": after_readmit_ping["ok"],
                    "session_state": session2.state.value},
    }
    print()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
