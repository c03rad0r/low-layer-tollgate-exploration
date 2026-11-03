#!/usr/bin/env python3
"""Controller-driven capstone: the seller loop, not a hand-written sequence.

Same A-B-C chain as PD, but `SellerController` decides when to pause, resume and
evict from the session state. The host talks to B's control socket through
`fipsctl` inside the container (`DockerControl`), because the socket is not
mounted on the host.
"""

from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))

import exp_c  # noqa: E402
import pay_demo  # noqa: E402
from tollgate_fips.controller import ControllerConfig, SellerController  # noqa: E402
from tollgate_fips.fipsctl import Fipsctl  # noqa: E402
from tollgate_fips.gate import FipsGate  # noqa: E402
from tollgate_fips.runner import DockerRunner  # noqa: E402
from tollgate_fips.session import Session  # noqa: E402

A, B, C = "lt-pause-a", "lt-pause-b", "lt-pause-c"


class DockerControl:
    """The UnixControl surface, via `fipsctl` inside the node's container."""

    def __init__(self, container: str):
        self.container = container

    def set_forwarding(self, npub: str, allow: bool) -> dict:
        result = exp_c.docker_exec(
            self.container,
            ["fipsctl", "set-forwarding", npub, "allow" if allow else "block"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)

    def set_admission(self, npub: str, action: str) -> dict:
        result = exp_c.docker_exec(
            self.container, ["fipsctl", "admission", npub, action])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return json.loads(result.stdout)


def main() -> int:
    pay_demo.WORK.mkdir(parents=True, exist_ok=True)
    pay_demo.run([str(ROOT / "harness/mint/run-mint.sh")], capture_output=True)

    a = Fipsctl(DockerRunner(A))
    b = Fipsctl(DockerRunner(B))
    c = Fipsctl(DockerRunner(C))
    for name, client in (("a", a), ("b", b), ("c", c)):
        if exp_c.wait_for(lambda cl=client: exp_c.running(cl), 20)[0] is None:
            raise RuntimeError(f"{name} daemon did not come up")

    a_npub = a.status()["npub"]
    b_npub = b.status()["npub"]
    c_npub = c.status()["npub"]
    b_addr = b.status()["ipv6_addr"]
    c_addr = c.status()["ipv6_addr"]

    if exp_c.wait_for(lambda: exp_c.peer_for(a, b_npub)
                      and exp_c.peer_for(c, b_npub), 25)[0] is None:
        raise RuntimeError("chain links did not form")
    exp_c.docker_exec(A, ["fipsctl", "probe", c_npub], timeout=40)

    gate = FipsGate(b, control=DockerControl(B))
    session = Session(npub=a_npub, rate_bytes_per_msat=Decimal("1"),
                      allotment_msat=Decimal(0), grace_seconds=30.0)
    controller = SellerController(
        gate, session,
        ControllerConfig(rate_bytes_per_msat=Decimal("1"), tick_seconds=0.1),
    )

    # 1. Unpaid: block transit, keep the link. Admission alone is not enough:
    # it gates new handshakes, and the link is already up. This is the `unpaid`
    # state the design wants: the buyer can reach the seller locally (checkout)
    # but not transit.
    gate.pause(a_npub)
    time.sleep(0.3)
    unpaid_ac = exp_c.ping6(A, c_addr, count=2)
    unpaid_ab = exp_c.ping6(A, b_addr, count=2)
    print(f"unpaid: a->c={unpaid_ac['ok']} a->b={unpaid_ab['ok']}")

    # 2. Real offline payment, then admit at runtime.
    token = pay_demo.mint_token(50, "token-controller.txt")
    keys = pay_demo.WORK / "keys.json"
    pay_demo.cache_keys(token, keys)
    pay_demo.mint_stop()
    receipt = pay_demo.gate_token(
        token, keys, f"ctrl-{int(time.time())}", a_npub, b_npub)
    pay_demo.mint_start()
    gate.admit(a_npub)
    controller.on_payment(Decimal(receipt["amount"]) * 1000)
    pay_demo.ensure_transit(c_npub, c_addr)
    print(f"paid: a->c={exp_c.ping6(A, c_addr, count=1)['ok']}")

    # 3. Run the seller loop while the buyer sends one packet per tick.
    ticks = 0
    while session.state.value == "paid" and ticks < 200:
        exp_c.ping6(A, c_addr, count=1, size=1200)
        result = controller.tick()
        ticks += 1
        if result.actions:
            print(f"tick {ticks}: state={result.state} actions={result.actions}")
        if session.state.value != "paid":
            break
    paused_ac = exp_c.ping6(A, c_addr, count=2)
    paused_ab = exp_c.ping6(A, b_addr, count=2)
    loop_state = session.state.value
    loop_paused = controller.paused
    loop_used_msat = session.used_msat
    print(f"after loop: state={loop_state} paused={loop_paused} "
          f"a->c={paused_ac['ok']} a->b={paused_ab['ok']} ticks={ticks}")

    # 4. Second payment: the controller resumes.
    token2 = pay_demo.mint_token(50, "token-controller2.txt")
    pay_demo.cache_keys(token2, keys)
    pay_demo.mint_stop()
    receipt2 = pay_demo.gate_token(
        token2, keys, f"ctrl2-{int(time.time())}", a_npub, b_npub)
    pay_demo.mint_start()
    resumed = controller.on_payment(Decimal(receipt2["amount"]) * 1000)
    pay_demo.ensure_transit(c_npub, c_addr)
    resumed_ac = exp_c.ping6(A, c_addr, count=2)
    print(f"renewed: actions={resumed.actions} state={resumed.state} "
          f"a->c={resumed_ac['ok']}")

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "fips_version": b.status().get("version"),
        "nodes": {"a": a_npub, "b": b_npub, "c": c_npub},
        "unpaid": {"a_to_c": unpaid_ac["ok"], "a_to_b": unpaid_ab["ok"]},
        "payment_1": {k: receipt[k] for k in
                      ("offline", "accepted", "amount",
                       "replay_before_settle", "replay_after_settle")},
        "loop": {
            "ticks": ticks,
            "state": loop_state,
            "paused": loop_paused,
            "a_to_c": paused_ac["ok"],
            "a_to_b": paused_ab["ok"],
            "used_msat": str(loop_used_msat),
            "allotment_msat": str(Decimal("50000")),
        },
        "payment_2": {k: receipt2[k] for k in
                      ("offline", "accepted", "amount",
                       "replay_before_settle", "replay_after_settle")},
        "renewed": {"actions": resumed.actions, "state": resumed.state,
                    "a_to_c": resumed_ac["ok"]},
        "evicted": controller.evicted,
    }
    print()
    print(json.dumps(summary, indent=2))
    ok = (not unpaid_ac["ok"] and unpaid_ab["ok"]
          and loop_state == "grace" and loop_paused
          and not paused_ac["ok"] and paused_ab["ok"]
          and resumed_ac["ok"] and not controller.evicted)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
