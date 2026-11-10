#!/usr/bin/env python3
"""Demonstrate durable account, strict P2PK and CRC-journal behavior.

Run without arguments to perform the `accept` and `resume` phases in **separate
child processes** and print one JSON summary. Does not contact a mint or claim
to prove MCU flash timing. All monetary values are synthetic test units.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sidecar"))

from tollgate_fips.account import PrepaidAccountStore
from tollgate_fips.appendlog import CrcJournal
from tollgate_fips.journal import AlreadySettled, ReservationInFlight
from tollgate_fips.nut11 import (
    OfflineProofRejected,
    check_offline_condition,
    require_compressed_lock_key,
)

SELLER_KEY = "02" + "ab" * 32


def run_account_phase(work: str) -> dict:
    store = PrepaidAccountStore(str(Path(work) / "accounts.sqlite3"))
    account = store.get_or_create("npub1payer", Decimal(1))
    account.top_up(Decimal(10000))
    account.link_up("npub1payer", "link-1")
    charged = account.charge(1230)
    account.link_down()
    store.save(account)
    before = {"state": account.state.value,
              "remaining_msat": str(account.remaining_msat),
              "charged_msat": str(charged), "link_id": account.link_id}
    store.close()
    return before


def resume_account_phase(work: str) -> dict:
    store = PrepaidAccountStore(str(Path(work) / "accounts.sqlite3"))
    account = store.get_or_create("npub1payer", Decimal(1))
    dormant = {"state": account.state.value,
               "remaining_msat": str(account.remaining_msat),
               "link_id": account.link_id}
    account.link_up("npub1payer", "link-9")
    account.top_up(Decimal(100))
    extra = account.charge(77)
    output = {"on_reopen": dormant, "on_new_link": {
        "state": account.state.value, "link_id": account.link_id,
        "remaining_msat": str(account.remaining_msat),
        "used_msat": str(account.used_msat), "charge_now_msat": str(extra)}}
    store.save(account)
    store.close()
    return output


def require_seller_lock() -> dict:
    require_compressed_lock_key(SELLER_KEY)
    valid = ["P2PK", {"data": SELLER_KEY, "nonce": "00" * 16,
                      "tags": [["sigflag", "SIG_INPUTS"]]}]
    check_offline_condition(valid, SELLER_KEY, final_expiry=None)
    result = {"valid_one_of_one": "accepted"}
    for name, tags in {
        "refund_reclaim": [["refund", "03" + "cd" * 32]],
        "locktime_reclaim": [["locktime", "1799999999"]],
        "grouped_signing": [["sigflag", "SIG_ALL"]],
        "unknown_extension": [["future_reclaim", "1"]],
    }.items():
        with_lock = ["P2PK", {**valid[1], "tags": tags}]
        try:
            check_offline_condition(with_lock, SELLER_KEY, final_expiry=None)
            result[name] = "ACCEPTED (unexpected)"
        except OfflineProofRejected as exc:
            result[name] = f"rejected: {exc}"
    return result


def require_journal(work: str) -> dict:
    path = Path(work) / "proofs.fjnl"
    journal = CrcJournal(str(path))
    journal.reserve(mint_url="http://mint", unit="sat", keyset_id="k1",
                    nullifier="demo-proof", amount_msat=100)
    try:
        journal.reserve(mint_url="http://mint", unit="sat", keyset_id="k1",
                        nullifier="demo-proof", amount_msat=100)
        replay = "accepted (unexpected)"
    except ReservationInFlight:
        replay = "ReservationInFlight"
    journal.settle("http://mint", "sat", "k1", "demo-proof")
    journal = CrcJournal(str(path))
    try:
        journal.reserve(mint_url="http://mint", unit="sat", keyset_id="k1",
                        nullifier="demo-proof", amount_msat=100)
        after = "accepted (unexpected)"
    except AlreadySettled:
        after = "AlreadySettled"

    truncated = Path(work) / "torn.fjnl"
    CrcJournal(str(truncated)).reserve(
        mint_url="http://mint", unit="sat", keyset_id="k1",
        nullifier="torn-proof", amount_msat=100)
    with truncated.open("r+b") as handle:
        handle.truncate(truncated.stat().st_size - 1)
    torn = CrcJournal(str(truncated))
    return {"replay_same_process": replay, "replay_after_reopen": after,
            "pending_after_settle": len(journal.pending()),
            "torn_tail_pending": len(torn.pending()),
            "records_after_reopen": len(journal.records())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["accept", "resume"])
    parser.add_argument("--work")
    args = parser.parse_args()
    if args.phase:
        if not args.work:
            parser.error("--work is required with --phase")
        if args.phase == "accept":
            print(json.dumps(run_account_phase(args.work), indent=2))
            return 0
        print(json.dumps(resume_account_phase(args.work), indent=2))
        return 0

    work = args.work or tempfile.mkdtemp(prefix="balloon-account-", dir="/tmp/opencode")
    Path(work).mkdir(parents=True, exist_ok=True)
    output = {}
    for phase in ("accept", "resume"):
        command = [sys.executable, str(Path(__file__)),
                   "--phase", phase, "--work", work]
        output[phase] = json.loads(subprocess.check_output(command, text=True))
    summary = {"work": work, **output,
               "offline_p2pk": require_seller_lock(),
               "crc_journal": require_journal(work)}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
