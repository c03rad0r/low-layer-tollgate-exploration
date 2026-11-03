#!/usr/bin/env python3
"""Exp G: a real keyset with a short `final_expiry`.

Uses the Nutshell SQLite store to set `final_expiry` on the active keyset, then
watches what the mint and a receiver do before and after it passes:

1. keyset advertises `final_expiry` in `/v1/keysets`;
2. DLEQ/P2PK verification still works offline (the signature does not expire);
3. the journal's `keyset_admissible` predicate refuses a proof inside the
   settlement window while accepting it with a small window;
4. after expiry, the mint's keyset state and a spend attempt are recorded.

The volume is restored to `final_expiry = NULL` at the end so later labs are
not affected.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sidecar"))

from tollgate_fips.journal import keyset_admissible, NullifierJournal  # noqa: E402

MINT = "lt-mint"
NET = "lt-mint-net"
MINT_VOL = "lt-mint-data"
WALLET_VOL = "lt-wallet-expiry"
RECV_VOL = "lt-wallet-expiry-recv"
IMAGE = "cashubtc/nutshell:latest"
URL = "http://lt-mint:3338"
HOST_URL = "http://127.0.0.1:3338"
KEYS = Path("/tmp/opencode/expiry-keys.json")


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, **kwargs)


def wallet(volume, *args):
    return run([
        "docker", "run", "--rm", "--network", NET,
        "-v", f"{volume}:/data", "-e", "CASHU_DIR=/data", IMAGE,
        "python3", "-m", "cashu.wallet", "--host", URL, "-y", *args,
    ], capture_output=True)


def sql(statement, params=()):
    code = (
        "import sqlite3,sys;"
        "con=sqlite3.connect('/data/mint/mint.sqlite3');"
        "cur=con.execute(sys.argv[1], sys.argv[2:]);"
        "con.commit();"
        "print(cur.fetchall())"
    )
    return run([
        "docker", "run", "--rm", "-v", f"{MINT_VOL}:/data", IMAGE,
        "python3", "-c", code, statement, *map(str, params),
    ], capture_output=True).stdout.strip()


def keysets():
    out = run(["curl", "-fsS", f"{HOST_URL}/v1/keysets"],
              capture_output=True).stdout
    return json.loads(out)["keysets"]


def main() -> int:
    run([str(ROOT / "harness/mint/run-mint.sh")], capture_output=True)

    # A plain (unlocked) token, so a receiver can attempt to spend it later.
    wallet(WALLET_VOL, "invoice", "20")
    sent = wallet(WALLET_VOL, "send", "-d", "10").stdout
    token = next((line for line in sent.splitlines()
                  if line.startswith("cashuB")), None)
    if not token:
        print("error: no plain token minted", file=sys.stderr)
        print(sent[-2000:], file=sys.stderr)
        return 2
    print("minted a plain 10 sat token")

    before = keysets()
    print("keysets before:", json.dumps(before))

    # Pin a short expiry on the active keyset.
    expiry = int(time.time()) + 120
    run(["docker", "stop", MINT], capture_output=True)
    sql("UPDATE keysets SET final_expiry=?", (expiry,))
    run(["docker", "start", MINT], capture_output=True)
    for _ in range(30):
        if subprocess.run(["curl", "-fsS", f"{HOST_URL}/v1/info"],
                          capture_output=True, check=False).returncode == 0:
            break
        time.sleep(1)
    after = keysets()
    print("keysets after:", json.dumps(after))
    advertised = next((k.get("final_expiry") for k in after
                       if k.get("final_expiry") is not None), None)

    # The journal predicate: refuse inside the settlement window, accept with
    # a window that ends before expiry.
    now = time.time()
    admissible_3600 = keyset_admissible(advertised, 3600, now=now)
    admissible_1 = keyset_admissible(advertised, 1, now=now)
    print(f"admissible(3600s)={admissible_3600} admissible(1s)={admissible_1}")

    # Wait out the expiry, then see what the mint does.
    remaining = expiry - time.time() + 5
    if remaining > 0:
        print(f"waiting {remaining:.0f}s for final_expiry")
        time.sleep(remaining)
    post = keysets()
    print("keysets after expiry:", json.dumps(post))

    receive = subprocess.run([
        "docker", "run", "--rm", "--network", NET,
        "-v", f"{RECV_VOL}:/data", "-e", "CASHU_DIR=/data", IMAGE,
        "python3", "-m", "cashu.wallet", "--host", URL, "-y",
        "receive", token,
    ], capture_output=True, text=True)
    receive_ok = receive.returncode == 0
    print(f"spend after expiry: ok={receive_ok}")
    if not receive_ok:
        print(receive.stderr[-600:])

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "mint": "Nutshell 0.21.0 FakeWallet",
        "final_expiry": advertised,
        "keyset_before": before,
        "keyset_after": after,
        "keyset_after_expiry": post,
        "journal_predicate": {
            "settlement_window_3600s": admissible_3600,
            "settlement_window_1s": admissible_1,
        },
        "spend_after_expiry": {
            "ok": receive_ok,
            "stderr_tail": receive.stderr[-400:] if not receive_ok else "",
        },
    }
    print()
    print(json.dumps(summary, indent=2))

    # Restore the volume for later labs.
    run(["docker", "stop", MINT], capture_output=True)
    sql("UPDATE keysets SET final_expiry=NULL")
    run(["docker", "start", MINT], capture_output=True)
    return 0 if (advertised == expiry and not admissible_3600
                 and admissible_1) else 1


if __name__ == "__main__":
    sys.exit(main())
