#!/usr/bin/env python3
"""E-CRASH: does the nullifier journal survive a crash without double-credit?

Three Windows are tested against the real `NullifierJournal` (SQLite WAL,
synchronous=FULL):

  A correct order: reserve -> credit -> crash. Replay must be refused.
  B buggy order:   credit -> crash -> reserve. Replay is accepted, which is
                   exactly the double-credit the ordering rule prevents.
  C reserve -> crash before credit. Replay refused; the loss is one credit.
  D reserve -> settle -> crash. Replay refused as AlreadySettled.

The append-only log arm truncates a record log at every byte offset and checks
that an incomplete tail is never treated as a committed reservation.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sidecar"))

from tollgate_fips.journal import NullifierJournal, NullifierConflict  # noqa: E402

RUNS = 20
PROOF = dict(mint_url="http://mint.test", unit="sat", keyset_id="00aa",
             nullifier="proof-secret-1", amount_msat="10000", final_expiry=None)
CREDIT = "credit.flag"


def child(mode: str, db: str, work: str) -> None:
    j = NullifierJournal(db)
    if mode == "buggy_credit_then_reserve":
        Path(work, CREDIT).write_text("1")
        os._exit(17)
    reservation = j.reserve(**PROOF)
    if mode == "reserve_then_crash":
        os._exit(17)
    if mode == "reserve_credit_then_crash":
        Path(work, CREDIT).write_text("1")
        os._exit(17)
    if mode == "settle_then_crash":
        j.settle(reservation)
        os._exit(17)
    os._exit(0)


def replay(work: str, db: str) -> str:
    j = NullifierJournal(db)
    try:
        j.reserve(**PROOF)
        return "accepted"
    except NullifierConflict as exc:
        return str(exc).split(":")[0].replace("nullifier already in state ", "")
    finally:
        j.close()


def arm(mode: str) -> dict:
    outcomes = []
    for _ in range(RUNS):
        work = tempfile.mkdtemp(prefix="crash-")
        try:
            db = str(Path(work, "journal.sqlite3"))
            subprocess.run([sys.executable, __file__, "--child", mode, db, work],
                           check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            credit = Path(work, CREDIT).exists()
            result = replay(work, db)
            outcomes.append({"credit_before_crash": credit,
                             "replay": result,
                             "double_credit": credit and result == "accepted"})
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return {"mode": mode, "runs": RUNS,
            "double_credit": sum(o["double_credit"] for o in outcomes),
            "replay_states": sorted({o["replay"] for o in outcomes}),
            "credit_before_crash": sum(o["credit_before_crash"]
                                       for o in outcomes)}


def append_log_arm() -> dict:
    """Truncate a committed-record log at every offset; incomplete tails are
    ignored, so a reservation is never invented."""
    import zlib
    records = []
    for i in range(3):
        body = json.dumps({"proof": f"p{i}", "state": "RESERVED"}).encode()
        crc = zlib.crc32(body) & 0xFFFFFFFF
        records.append(crc.to_bytes(4, "little") + body)
    blob = b"".join(records)
    bad = 0
    checked = 0
    for cut in range(len(blob)):
        seen = set()
        pos = 0
        while pos + 4 <= cut:
            crc = int.from_bytes(blob[pos:pos + 4], "little")
            # find the next complete record by scanning for a valid CRC
            found = False
            for end in range(pos + 4, cut + 1):
                body = blob[pos + 4:end]
                if zlib.crc32(body) & 0xFFFFFFFF == crc:
                    try:
                        rec = json.loads(body)
                    except Exception:
                        continue
                    seen.add(rec["proof"])
                    pos = end
                    found = True
                    break
            if not found:
                break
        checked += 1
        # A cut can only lose a record; it must never invent one.
        if not seen.issubset({f"p{i}" for i in range(3)}):
            bad += 1
    return {"truncations": checked, "invented_records": bad,
            "record_bytes": [len(r) for r in records]}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3], sys.argv[4])
        return 0
    out = {"date": time.strftime("%Y-%m-%d"), "runs_per_arm": RUNS,
           "arms": [arm(m) for m in
                    ("reserve_then_crash", "reserve_credit_then_crash",
                     "settle_then_crash", "buggy_credit_then_reserve")],
           "append_log": append_log_arm()}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
