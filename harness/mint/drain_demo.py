#!/usr/bin/env python3
"""Background drain: accept one token, crash, let the daemon settle it.

Runs inside the Nutshell image. Mirrors `batch_redeem.py` but hands the vault to
`SettlementDaemon`, which polls until the pending set is empty.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import verify_token
from batch_redeem import LocalBatchRedeemer
from gate_token import VerifiedJSON, proofs_from_result

from tollgate_fips.drain import SettlementDaemon
from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.payment import PaymentGate
from tollgate_fips.settlement import SettlementWorker
from tollgate_fips.vault import TokenVault


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("token_file")
    parser.add_argument("--keys-file", required=True)
    parser.add_argument("--seller-pubkey", required=True)
    parser.add_argument("--seller-npub", required=True)
    parser.add_argument("--seller-nsec", required=True)
    parser.add_argument("--mint", default="http://lt-mint:3338")
    parser.add_argument("--buyer-npub", default="npub1testbuyer")
    parser.add_argument("--db-dir", default="/data/drain")
    parser.add_argument("--wallet-dir", default="/data/drain-wallet")
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--cap-msat", default="1000000")
    args = parser.parse_args()

    token_str = Path(args.token_file).read_text().strip().splitlines()[0]
    cache = verify_token.fetch_keysets(args.mint, args.keys_file)
    verified = verify_token.verify(token_str, cache, args.seller_pubkey,
                                   args.mint, settlement_window=3600)
    if not verified["ok"]:
        print(json.dumps({"verify_ok": False,
                          "problems": verified["problems"]}, indent=2))
        return 1

    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    journal = NullifierJournal(str(db_dir / "journal.sqlite3"))
    exposure = ExposureLedger(str(db_dir / "exposure.sqlite3"))
    vault = TokenVault(str(db_dir / "vault.sqlite3"))
    gate = PaymentGate(journal, exposure, VerifiedJSON(), args.seller_npub,
                       cap_msat=args.cap_msat, settlement_window_secs=3600)
    proofs = proofs_from_result(verified, args.buyer_npub)
    for proof in proofs:
        gate.accept(proof, "msg1-test", vault=vault, token=token_str)
    exposure_key = ExposureKey(args.buyer_npub, args.mint, "sat")
    before = {"vault": len(vault.pending()),
              "exposure": str(exposure.outstanding(exposure_key))}

    # Simulated crash: the daemon starts from reopened files only.
    journal.close()
    exposure.close()
    vault.close()
    journal = NullifierJournal(str(db_dir / "journal.sqlite3"))
    exposure = ExposureLedger(str(db_dir / "exposure.sqlite3"))
    vault = TokenVault(str(db_dir / "vault.sqlite3"))

    worker = SettlementWorker(
        journal, exposure,
        LocalBatchRedeemer(args.mint, args.seller_nsec, args.wallet_dir))
    daemon = SettlementDaemon(vault, worker, poll_seconds=args.poll,
                              batch_size=10)
    sleep_calls = []

    def sleeper(seconds):
        sleep_calls.append(seconds)
        time.sleep(seconds)

    daemon.sleep = sleeper
    stats = daemon.run(stop=lambda: not vault.pending(), max_passes=5)

    after = {"vault": len(vault.pending()),
             "exposure": str(exposure.outstanding(exposure_key))}
    states = [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
              for p in proofs]
    journal.close()
    exposure.close()
    vault.close()

    summary = {
        "proofs": len(proofs),
        "before": before,
        "after": after,
        "passes": stats.passes,
        "settled": stats.settled,
        "failed": stats.failed,
        "fee_sat": stats.fee_sat,
        "sleeps": sleep_calls,
        "journal": states,
        "errors": stats.errors,
    }
    print(json.dumps(summary, indent=2))
    ok = (after["vault"] == 0 and after["exposure"] == "0"
          and stats.settled == len(proofs)
          and states == ["SETTLED"] * len(proofs))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
