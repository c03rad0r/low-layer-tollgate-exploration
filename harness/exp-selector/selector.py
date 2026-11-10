#!/usr/bin/env python3
"""E-SELECTOR: can an L0 allow-list follow a UDP rebind?

The seller allows only the buyer's current 5-tuple (IP + source port) to reach
FIPS UDP/2121. The buyer then changes its bind port from 2121 to 2222. The
seller drops the new handshake because the allow-list still names 2121, and it
cannot learn the new port from packets it is dropping. The rule is updated
out of band and the link recovers.
"""
from __future__ import annotations
import json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness" / "exp-c"))
sys.path.insert(0, str(ROOT / "sidecar"))
import exp_c
from tollgate_fips.fipsctl import Fipsctl
from tollgate_fips.runner import DockerRunner

SELLER, BUYER = "lt-sel-seller", "lt-sel-buyer"
CFG = Path(__file__).parent / "configs" / "buyer.yaml"


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)


def buyer_ip() -> str:
    out = sh(f"docker inspect -f '{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}}{{{{end}}}}' {BUYER}").stdout.strip()
    return out


def nft_allow(ip: str, sport: int) -> None:
    # Reset our table, then allow exactly one 5-tuple and drop the rest.
    cmd = (
        "nft delete table inet sel 2>/dev/null || :; "
        "nft add table inet sel; "
        "nft add chain inet sel input '{ type filter hook input priority 0; policy accept; }'; "
        f"nft add rule inet sel input udp dport 2121 ip saddr {ip} udp sport {sport} accept; "
        "nft add rule inet sel input udp dport 2121 drop"
    )
    r = sh(f"docker exec {SELLER} sh -lc {json.dumps(cmd)}")
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    print("nft allow:", ip, sport)

def wait_link(fips: Fipsctl, npub: str, timeout: float = 40):
    return exp_c.wait_for(lambda: exp_c.peer_for(fips, npub), timeout)


def main() -> int:
    seller = Fipsctl(DockerRunner(SELLER))
    buyer = Fipsctl(DockerRunner(BUYER))
    for name, cl in (("seller", seller), ("buyer", buyer)):
        if exp_c.wait_for(lambda c=cl: exp_c.running(c), 25)[0] is None:
            raise RuntimeError(f"{name} did not start")
    s = seller.status(); b = buyer.status()
    print("seller", s["npub"], "buyer", b["npub"], "buyer_ip", buyer_ip())
    if wait_link(seller, b["npub"], 40)[0] is None:
        raise RuntimeError("baseline link did not form")
    ip = buyer_ip()
    nft_allow(ip, 2121)

    # Baseline after the allow-list is installed.
    base = exp_c.ping6(SELLER, b["ipv6_addr"], count=3)
    print("baseline ping:", base["ok"], base["loss_pct"])

    # Rebind the buyer to 2222.
    cfg = CFG.read_text()
    CFG.write_text(cfg.replace('bind_addr: "0.0.0.0:2121"',
                               'bind_addr: "0.0.0.0:2222"'))
    sh(f"docker restart {BUYER}")
    # Wait for the daemon, then a fixed observation window.
    for _ in range(30):
        if sh(f"docker exec {BUYER} fipsctl show status").returncode == 0:
            break
        time.sleep(0.5)
    t0 = time.monotonic()
    time.sleep(12)
    dropped = exp_c.ping6(SELLER, b["ipv6_addr"], count=2)
    print("after rebind (old rule):", dropped["ok"], dropped["loss_pct"])

    # Out-of-band update to the new selector, as a control plane must do.
    nft_allow(ip, 2222)
    t_update = time.monotonic()
    waited, _ = wait_link(seller, b["npub"], 40)
    recovered = exp_c.ping6(SELLER, b["ipv6_addr"], count=3)
    print("recovered:", waited is not None,
          "after_update_s:", round(time.monotonic() - t_update, 2),
          "ping:", recovered["ok"], recovered["loss_pct"])

    out = {
        "buyer_ip": ip,
        "old_selector": f"{ip}:2121",
        "new_selector": f"{ip}:2222",
        "baseline_ok": base["ok"],
        "old_rule_after_rebind_ok": dropped["ok"],
        "recovered": waited is not None,
        "blackout_s_before_update": round(t_update - t0, 2),
        "recovery_s_after_update": round(time.monotonic() - t_update, 2),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(out, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
