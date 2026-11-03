#!/usr/bin/env python3
"""Feed a real verified token through PaymentGate, journal and exposure.

Lab adapter: `verify_token.py` does the DLEQ/P2PK checks, then this script turns
each proof into a PaymentProof and exercises:

  accept -> journal RESERVED + exposure outstanding
  reopen the databases (simulated restart)
  replay -> ReservationInFlight
  settle -> journal SETTLED + exposure released
  replay again -> AlreadySettled

It runs inside the Nutshell image (cashu + sidecar mounted). The verifier is a
JSON adapter, not a production Cashu verifier.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

import verify_token

from tollgate_fips.exposure import ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.payment import PaymentGate, PaymentProof


class VerifiedJSON:
    """Verifier adapter for an already-verified token.

    `verify_token.py` has checked DLEQ and the P2PK lock. This adapter only
    relays that per-proof result; it is not a substitute for the real verifier.
    """

    def verify(self, proof, seller_npub, msg1_ephemeral):
        token = proof.token or {}
        return bool(token.get("dleq_valid") and token.get("p2pk_lock_ok"))


def proofs_from_result(result, payer_npub: str):
    final_expiry = None
    expiries = [e for e in result.get("keyset_final_expiry", []) if e is not None]
    if expiries:
        final_expiry = min(expiries)
    out = []
    for item in result["proofs"]:
        out.append(PaymentProof(
            mint_url=result["mint"],
            unit=result["unit"],
            keyset_id=item["keyset_id"],
            nullifier=item["nullifier"],
            amount_msat=Decimal(item["amount"]) * 1000,
            payer_npub=payer_npub,
            final_expiry=final_expiry,
            token=item,
        ))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("token_file")
    parser.add_argument("--keys-file", required=True)
    parser.add_argument("--seller-pubkey", required=True)
    parser.add_argument("--mint", default="http://lt-mint:3338")
    parser.add_argument("--buyer-npub", default="npub1testbuyer")
    parser.add_argument("--seller-npub", default="npub1testseller")
    parser.add_argument("--db-dir", default="/data/f-gate")
    parser.add_argument("--cap-msat", default="100000")
    args = parser.parse_args()

    token = Path(args.token_file).read_text().strip().splitlines()[0]
    cache = verify_token.fetch_keysets(args.mint, args.keys_file)
    result = verify_token.verify(token, cache, args.seller_pubkey,
                                 args.mint, settlement_window=3600)
    if not result["ok"]:
        print(json.dumps({"verify_ok": False, "problems": result["problems"]},
                         indent=2))
        return 1

    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    journal_path = str(db_dir / "journal.sqlite3")
    exposure_path = str(db_dir / "exposure.sqlite3")

    proofs = proofs_from_result(result, args.buyer_npub)
    journal = NullifierJournal(journal_path)
    exposure = ExposureLedger(exposure_path)
    gate = PaymentGate(journal, exposure, VerifiedJSON(), args.seller_npub,
                       cap_msat=args.cap_msat,
                       settlement_window_secs=3600)
    receipts = []
    for proof in proofs:
        receipts.append(gate.accept(proof, "msg1-test", now=result["checked_at"]))
    states = [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
              for p in proofs]
    unique_keys = {r.exposure_key for r in receipts}
    outstanding = sum((exposure.outstanding(key) for key in unique_keys),
                      Decimal(0))
    journal.close()
    exposure.close()

    # Simulated restart: new connections, same files.
    journal = NullifierJournal(journal_path)
    exposure = ExposureLedger(exposure_path)
    gate = PaymentGate(journal, exposure, VerifiedJSON(), args.seller_npub,
                       cap_msat=args.cap_msat,
                       settlement_window_secs=3600)
    replay_before = None
    try:
        gate.accept(proofs[0], "msg1-test", now=result["checked_at"])
    except Exception as exc:  # noqa: BLE001 - report the class
        replay_before = type(exc).__name__

    for receipt in receipts:
        gate.settle(receipt)
    states_after = [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
                    for p in proofs]
    outstanding_after = sum(
        (exposure.outstanding(key) for key in unique_keys), Decimal(0))

    journal.close()
    exposure.close()
    journal = NullifierJournal(journal_path)
    exposure = ExposureLedger(exposure_path)
    gate = PaymentGate(journal, exposure, VerifiedJSON(), args.seller_npub,
                       cap_msat=args.cap_msat,
                       settlement_window_secs=3600)
    replay_after = None
    try:
        gate.accept(proofs[0], "msg1-test", now=result["checked_at"])
    except Exception as exc:  # noqa: BLE001
        replay_after = type(exc).__name__
    journal.close()
    exposure.close()

    summary = {
        "verify_ok": result["ok"],
        "offline": True,
        "mint": result["mint"],
        "amount": result["amount"],
        "proofs": len(proofs),
        "accepted": len(receipts),
        "journal_states": states,
        "exposure_outstanding_msat": str(outstanding),
        "replay_before_settle": replay_before,
        "settled": len(receipts),
        "journal_states_after_settle": states_after,
        "exposure_after_settle_msat": str(outstanding_after),
        "replay_after_settle": replay_after,
    }
    print(json.dumps(summary, indent=2))
    expected = (
        replay_before == "ReservationInFlight"
        and states_after == ["SETTLED"] * len(proofs)
        and outstanding_after == Decimal(0)
        and replay_after == "AlreadySettled"
    )
    return 0 if expected else 1


if __name__ == "__main__":
    sys.exit(main())
