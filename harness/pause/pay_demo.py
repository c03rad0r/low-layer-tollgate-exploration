#!/usr/bin/env python3
"""Capstone: unpaid enforced by patch (b), then pay, exhaust, pause, renew.

Chain A (buyer) -- B (seller) -- C (service). B is the patched transit node.

1. Unpaid: B blocks A's transit. A->C fails, A->B (local/payment lane) works.
2. Real offline payment: 50 sat P2PK+DLEQ token to B, verified with the mint
   stopped, accepted by PaymentGate/journal/exposure.
3. Allow: A->C works.
4. Traffic until the 50 sat allotment is exhausted.
5. Pause (patch b): A->C fails, A->B works, and the A-B link id is unchanged.
6. Second real token, allow again, A->C works. No disconnect at any point.

Payment is out-of-band; the payment gate runs on the host for lab convenience.
The patch is local and unmerged.
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
from tollgate_fips.meter import delta, snapshot  # noqa: E402
from tollgate_fips.runner import DockerRunner  # noqa: E402
from tollgate_fips.session import Session, State  # noqa: E402

A = os.environ.get("PAUSE_A", "lt-pause-a")
B = os.environ.get("PAUSE_B", "lt-pause-b")
C = os.environ.get("PAUSE_C", "lt-pause-c")
SELLER_PUBKEY = "REPLACE_WITH_HEX_SEEDff"
MINT_URL = "http://lt-mint:3338"
WORK = Path(os.environ.get("PAUSE_WORK", "/tmp/opencode/pause-pay"))
IMAGE = "cashubtc/nutshell:latest"


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def control(npub: str, allow: bool) -> dict:
    result = exp_c.docker_exec(
        B, ["python3", "/pause/control.py", npub, "allow" if allow else "block"])
    if result.returncode != 0:
        raise RuntimeError(f"control failed: {result.stderr.strip()}")
    return json.loads(result.stdout.strip())


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
            summary = json.loads(text[text.rindex("\n{\n"):])
        except (ValueError, json.JSONDecodeError):
            print(result.stdout[-3000:], file=sys.stderr)
            print(result.stderr[-3000:], file=sys.stderr)
            raise RuntimeError(f"gate_token.py failed (rc={result.returncode})")
    if result.returncode != 0 or not summary.get("verify_ok"):
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


def traffic(b: Fipsctl, a_npub: str, c_addr: str, count: int = 1) -> dict:
    """Ping C and price the window, excluding policy-dropped transit.

    The link counters include frames B refused to forward, so the policy
    counters are snapshotted over the same window and subtracted. `wire` is
    what the link saw; `billable` is what a gate may charge.
    """
    before = snapshot(b.peers(), b.links())
    policy_before = b.policy_blocked_for(a_npub)["bytes"]
    result = exp_c.ping6(A, c_addr, count=count, size=1200)
    time.sleep(0.05)
    after = snapshot(b.peers(), b.links())
    policy_after = b.policy_blocked_for(a_npub)["bytes"]
    readings = delta(
        before, after, Decimal("1"), "both",
        policy_previous={a_npub: policy_before},
        policy_current={a_npub: policy_after},
    )
    reading = next((r for r in readings if r.npub == a_npub), None)
    return {
        "wire": reading.wire_bytes if reading else 0,
        "in": reading.bytes_in if reading else 0,
        "out": reading.bytes_out if reading else 0,
        "dropped": reading.policy_dropped_bytes if reading else 0,
        "billable": reading.billable_bytes if reading else 0,
        "ok": result["ok"],
    }


def ensure_transit(c_npub: str, c_addr: str) -> dict:
    """Raw ICMP does not always re-establish a session; probe if needed."""
    last = {}
    for _ in range(10):
        last = exp_c.ping6(A, c_addr, count=1)
        if last["ok"]:
            return last
        time.sleep(0.5)
    exp_c.docker_exec(A, ["fipsctl", "probe", c_npub], timeout=40)
    for _ in range(10):
        last = exp_c.ping6(A, c_addr, count=1)
        if last["ok"]:
            return last
        time.sleep(0.5)
    return last


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    run([str(ROOT / "harness/mint/run-mint.sh")], capture_output=True)

    a = Fipsctl(DockerRunner(A))
    b = Fipsctl(DockerRunner(B))
    c = Fipsctl(DockerRunner(C))
    for name, client in (("a", a), ("b", b), ("c", c)):
        if exp_c.wait_for(lambda cl=client: exp_c.running(cl), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")
    a_status, b_status, c_status = a.status(), b.status(), c.status()
    a_npub, b_npub, c_npub = (s["npub"] for s in (a_status, b_status, c_status))
    b_addr = b_status["ipv6_addr"]
    c_addr = c_status["ipv6_addr"]

    _, pair = exp_c.wait_link(a, b, a_npub, b_npub, 20)
    if pair is None:
        raise RuntimeError("A-B link did not form")
    link_id_before = pair[0].get("link_id")
    if exp_c.wait_for(lambda: exp_c.peer_for(c, b_npub) and exp_c.peer_for(b, c_npub), 20)[0] is None:
        raise RuntimeError("B-C link did not form")

    # Warm discovery/session to C.
    exp_c.docker_exec(A, ["fipsctl", "probe", c_npub], timeout=40)

    # 1. Unpaid: block A's transit.
    unpaid_block = control(a_npub, allow=False)
    time.sleep(0.3)
    unpaid_ac = exp_c.ping6(A, c_addr, count=2)
    unpaid_ab = exp_c.ping6(A, b_addr, count=2)
    print(f"unpaid: a->c={unpaid_ac['ok']} a->b={unpaid_ab['ok']} "
          f"block={unpaid_block['data']['forwarding']}")

    # 2. Real offline payment.
    token1 = mint_token(50, "token1.txt")
    keys = WORK / "keys.json"
    cache_keys(token1, keys)
    mint_stop()
    gate1 = gate_token(token1, keys, f"gate1-{int(time.time())}",
                       a_npub, b_npub)
    mint_start()
    token_msat = Decimal(gate1["amount"]) * 1000
    print(f"payment 1: offline={gate1['offline']} accepted={gate1['accepted']} "
          f"amount={gate1['amount']} sat")

    # 3. Allow and confirm transit.
    control(a_npub, allow=True)
    time.sleep(0.3)
    paid_ac = ensure_transit(c_npub, c_addr)
    if not paid_ac["ok"]:
        raise RuntimeError("transit did not recover after payment")
    print(f"paid: a->c={paid_ac['ok']}")

    link_id_pre_pause = exp_c.peer_for(b, a_npub).get("link_id")

    # 4. Traffic until the token's allowance is used.
    session = Session(npub=a_npub, rate_bytes_per_msat=Decimal("1"),
                      allotment_msat=Decimal(0), grace_seconds=30.0)
    session.pay(token_msat)
    total = 0
    pings = 0
    while session.state is State.PAID:
        step = traffic(b, a_npub, c_addr)
        if not step["ok"]:
            raise RuntimeError("transit failed during the paid session")
        if step["billable"] == 0:
            pings += 1
            if pings > 100:
                raise RuntimeError("no metered transit bytes")
            continue
        total += step["billable"]
        session.charge(step["billable"])
        pings += 1
        if pings > 100:
            raise RuntimeError("session did not exhaust")
    print(f"session: bytes={total} used={session.used_msat} msat "
          f"state={session.state.value} pings={pings}")

    # 5. Pause: block transit, keep the link.
    pause_started = time.monotonic()
    pause_block = control(a_npub, allow=False)
    time.sleep(0.3)
    pause_ac = exp_c.ping6(A, c_addr, count=2)
    pause_ab = exp_c.ping6(A, b_addr, count=2)
    pause_ms = (time.monotonic() - pause_started) * 1000
    link_id_paused = exp_c.peer_for(b, a_npub).get("link_id")
    print(f"pause: a->c={pause_ac['ok']} a->b={pause_ab['ok']} "
          f"link={link_id_paused} (pre={link_id_pre_pause}, {pause_ms:.0f} ms)")

    # While paused, the link counter still sees the frames B refuses to
    # forward. Attribute them to A and confirm none of them are billable.
    blocked = traffic(b, a_npub, c_addr, count=5)
    print(f"blocked burst: wire={blocked['wire']} dropped={blocked['dropped']} "
          f"billable={blocked['billable']}")

    # 6. Second payment, allow again.
    token2 = mint_token(50, "token2.txt")
    cache_keys(token2, keys)
    mint_stop()
    gate2 = gate_token(token2, keys, f"gate2-{int(time.time())}",
                       a_npub, b_npub)
    mint_start()
    control(a_npub, allow=True)
    time.sleep(0.3)
    resume_ac = ensure_transit(c_npub, c_addr)
    link_id_after = exp_c.peer_for(b, a_npub).get("link_id")
    print(f"payment 2: offline={gate2['offline']} accepted={gate2['accepted']} "
          f"amount={gate2['amount']} sat; a->c={resume_ac['ok']} "
          f"link={link_id_after}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": b_status.get("version"),
        "nodes": {"a": a_npub, "b": b_npub, "c": c_npub},
        "unpaid": {"a_to_c": unpaid_ac["ok"], "a_to_b": unpaid_ab["ok"],
                   "forwarding": unpaid_block["data"]["forwarding"]},
        "payment_1": {k: gate1[k] for k in
                      ("offline", "accepted", "amount",
                       "replay_before_settle", "replay_after_settle")},
        "paid": {"a_to_c": paid_ac["ok"]},
        "session": {"allotment_msat": str(token_msat),
                    "billable_bytes": total,
                    "used_msat": str(session.used_msat),
                    "overshoot_msat": str(session.used_msat - token_msat),
                    "pings": pings, "state": session.state.value},
        "pause": {"a_to_c": pause_ac["ok"], "a_to_b": pause_ab["ok"],
                  "forwarding": pause_block["data"]["forwarding"],
                  "pause_ms": round(pause_ms),
                  "link_id": link_id_paused,
                  "link_id_pre_pause": link_id_pre_pause,
                  "link_preserved": link_id_paused == link_id_pre_pause,
                  "blocked_burst": blocked},
        "payment_2": {k: gate2[k] for k in
                      ("offline", "accepted", "amount",
                       "replay_before_settle", "replay_after_settle")},
        "resume": {"a_to_c": resume_ac["ok"], "link_id": link_id_after,
                   "link_id_preserved": link_id_after == link_id_pre_pause},
        "link_id_before": link_id_before,
        "link_id_pre_pause": link_id_pre_pause,
    }
    print()
    print(json.dumps(summary, indent=2))
    ok = (not unpaid_ac["ok"] and unpaid_ab["ok"]
          and paid_ac["ok"]
          and not pause_ac["ok"] and pause_ab["ok"]
          and resume_ac["ok"]
          and link_id_paused == link_id_pre_pause == link_id_after
          and blocked["dropped"] > 0
          and blocked["billable"] == max(0, blocked["in"] - blocked["dropped"])
          + blocked["out"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
