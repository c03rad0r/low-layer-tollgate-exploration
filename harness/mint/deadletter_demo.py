#!/usr/bin/env python3
"""Dead-letter + recovery: a mint outage parks a token, then it settles.

Runs inside the Nutshell image. The flow:

  1. verify and accept a 10 sat P2PK token into the vault (2 proofs,
     journal RESERVED, exposure 10,000 msat);
  2. close/reopen the databases (simulated crash);
  3. run the drain against an unreachable mint URL for `max_attempts` passes;
     every pass fails, the rows are dead-lettered, exposure is untouched;
  4. inspect `health()` and the dead-letter list;
  5. requeue the rows, point the same worker at the real mint, run one pass;
  6. journal SETTLED, exposure 0, vault empty, NUT-07 inputs SPENT.

This exercises the failure mode a background drain must survive: the mint is
down long enough that retrying at full rate is wrong, but the money is still
good and must settle once the mint returns.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import httpx
import verify_token
from batch_redeem import LocalBatchRedeemer, checkstate
from gate_token import VerifiedJSON, proofs_from_result

from tollgate_fips.drain import SettlementDaemon
from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.payment import PaymentGate
from tollgate_fips.settlement import SettlementWorker
from tollgate_fips.vault import TokenVault


class UnreachableRedeemer:
    """A redeemer whose mint is down, with an explicit error message."""

    def __init__(self, mint_url: str):
        self.mint_url = mint_url

    def redeem(self, token: str) -> dict:
        return self.redeem_many([token])

    def redeem_many(self, tokens) -> dict:
        try:
            httpx.get(f"{self.mint_url}/v1/info", timeout=1.0)
        except Exception as exc:  # noqa: BLE001 - the point is the failure
            return {"ok": False,
                    "error": f"mint unreachable: {type(exc).__name__}: {exc}"}
        return {"ok": False,
                "error": f"mint at {self.mint_url} is not the settlement mint"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("token_file")
    parser.add_argument("--keys-file", required=True)
    parser.add_argument("--seller-pubkey", required=True)
    parser.add_argument("--seller-npub", required=True)
    parser.add_argument("--seller-nsec", required=True)
    parser.add_argument("--mint", default="http://lt-mint:3338")
    parser.add_argument("--bad-mint", default="http://lt-mint:9999")
    parser.add_argument("--buyer-npub", default="npub1testbuyer")
    parser.add_argument("--db-dir", default="/data/deadletter")
    parser.add_argument("--wallet-dir", default="/data/deadletter-wallet")
    parser.add_argument("--bad-wallet-dir", default="/data/deadletter-bad")
    parser.add_argument("--max-attempts", type=int, default=3)
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
    before = {
        "vault_pending": len(vault.pending()),
        "exposure_msat": str(exposure.outstanding(exposure_key)),
        "journal": [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
                    for p in proofs],
    }

    # Simulated crash: the daemon starts from reopened files only.
    journal.close()
    exposure.close()
    vault.close()
    journal = NullifierJournal(str(db_dir / "journal.sqlite3"))
    exposure = ExposureLedger(str(db_dir / "exposure.sqlite3"))
    vault = TokenVault(str(db_dir / "vault.sqlite3"))

    # 1. Mint is down: every pass fails.
    worker = SettlementWorker(
        journal, exposure, UnreachableRedeemer(args.bad_mint))
    daemon = SettlementDaemon(vault, worker, poll_seconds=args.poll,
                              max_attempts=args.max_attempts,
                              sleep=lambda _: None)
    passes = []
    for _ in range(args.max_attempts):
        daemon.run_once()
        passes.append(daemon.health().as_dict())

    outage = {
        "pending": len(vault.pending()),
        "dead_lettered": len(vault.dead_lettered()),
        "exposure_msat": str(exposure.outstanding(exposure_key)),
        "journal": [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
                    for p in proofs],
        "health": daemon.health().as_dict(),
    }

    # 2. Operator requeues after the mint returns and swaps in the real redeemer.
    dead_keys = [entry.vault_key for entry in daemon.dead_letters()]
    for key in dead_keys:
        daemon.requeue(key)
    worker.redeemer = LocalBatchRedeemer(args.mint, args.seller_nsec,
                                         args.wallet_dir)
    result = daemon.run_once()

    after = {
        "pending": len(vault.pending()),
        "dead_lettered": len(vault.dead_lettered()),
        "exposure_msat": str(exposure.outstanding(exposure_key)),
        "journal": [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
                    for p in proofs],
        "settled": result.settled,
        "failed": result.failed,
        "health": daemon.health().as_dict(),
    }
    states = checkstate(args.mint, [token_str])

    journal.close()
    exposure.close()
    vault.close()

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "proofs": len(proofs),
        "max_attempts": args.max_attempts,
        "before": before,
        "outage_health_by_pass": passes,
        "outage": outage,
        "recovered": after,
        "nut07": states,
    }
    print(json.dumps(summary, indent=2))
    ok = (
        outage["pending"] == 0
        and outage["dead_lettered"] == len(proofs)
        and outage["exposure_msat"] == before["exposure_msat"]
        and after["pending"] == 0
        and after["dead_lettered"] == 0
        and after["exposure_msat"] == "0"
        and after["settled"] == len(proofs)
        and after["failed"] == 0
        and states["all_spent"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
