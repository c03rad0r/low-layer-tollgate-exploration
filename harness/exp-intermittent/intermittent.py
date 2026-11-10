#!/usr/bin/env python3
"""E-INTERMITTENT: does a paid session survive a 90-second contact gap?

Two sessions see exactly the same physical buyer stop/start: a link-scoped
session with a 60-second absolute deadline, and an account-like session with a
7200-second deadline. A stop/start reconnects the FIPS link but changes its id.
"""
from __future__ import annotations
import json, subprocess, sys, time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))
import exp_c
from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.runner import DockerRunner
from tollgate_fips.session import Session

SELLER, BUYER = "lt-int-seller", "lt-int-buyer"
GAP = 90


def wait_daemon(container: str, timeout=40):
    start=time.monotonic(); last=None
    while time.monotonic()-start < timeout:
        result=subprocess.run(["docker","exec",container,"fipsctl","show","status"],text=True,capture_output=True)
        if result.returncode==0:
            return last
        time.sleep(1)
    return last


def run_arm(label: str, max_seconds: float, gap: int) -> dict:
    seller=Fipsctl(DockerRunner(SELLER)); buyer=Fipsctl(DockerRunner(BUYER))
    seller_npub=seller.status()["npub"]; buyer_npub=buyer.status()["npub"]
    exp_c.wait_for(lambda: exp_c.peer_for(seller,buyer_npub),60)
    peer0=exp_c.peer_for(seller,buyer_npub)
    session=Session(npub=buyer_npub, rate_bytes_per_msat=Decimal(1),
                    allotment_msat=Decimal(50000), grace_seconds=20,
                    max_session_seconds=max_seconds)
    session.pay(Decimal(50000))
    base=exp_c.ping6(BUYER,seller.status()["ipv6_addr"],count=3)
    print(f"{label}: before link={peer0.get('link_id')} ping={base['ok']}")
    subprocess.run(["docker","stop",BUYER],capture_output=True,check=True)
    t0=time.monotonic(); states=[["0",session.state.value]]
    while time.monotonic()-t0 < gap:
        time.sleep(10)
        elapsed=round(time.monotonic()-t0)
        state=session.tick()
        states.append([str(elapsed),state.value])
        print(f"{label}: gap={elapsed}s state={state.value}")
    subprocess.run(["docker","start",BUYER],capture_output=True,check=True)
    wait_daemon(BUYER,60)
    waited,_=exp_c.wait_for(lambda: exp_c.peer_for(seller,buyer_npub),60)
    peer1=exp_c.peer_for(seller,buyer_npub)
    final=session.tick()
    after=exp_c.ping6(BUYER,seller.status()["ipv6_addr"],count=3)
    out={"label":label,"max_session_seconds":max_seconds,"gap_s":gap,
         "before_link_id":peer0.get("link_id"),"after_link_id":peer1.get("link_id"),
         "reconnected":waited is not None,"after_ping_ok":after["ok"],
         "session_final":final.value,"remaining_msat":str(session.remaining_msat),
         "states":states}
    print(json.dumps(out))
    return out


def main() -> int:
    out=[run_arm("link-scoped-60s-deadline",60,GAP),
         run_arm("account-7200s-deadline",7200,GAP)]
    print(json.dumps(out,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
