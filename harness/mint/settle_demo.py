#!/usr/bin/env python3
"""Redeem an accepted P2PK token and settle the journal.

Runs inside the Nutshell image (cashu + sidecar + harness mounted):

  verify offline -> PaymentGate.accept (journal RESERVED, exposure outstanding)
  -> redeem with the seller's key (mint swap, inputs SPENT)
  -> SettlementWorker.settle (journal SETTLED, exposure 0)
  -> replay the token through the gate (AlreadySettled)
  -> NUT-07 checkstate on the original inputs (SPENT)

The seller nsec is a test identity; no real funds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import verify_token
from cashu.core.base import TokenV4
from cashu.core.crypto.secp import PrivateKey
from cashu.wallet.helpers import deserialize_token_from_string, receive
from cashu.wallet.wallet import Wallet
from gate_token import VerifiedJSON, proofs_from_result

from tollgate_fips.exposure import ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.payment import PaymentGate, PaymentProof
from tollgate_fips.settlement import SettlementWorker


class LocalCashuRedeemer:
    """Redeem a token with the seller's P2PK key using the cashu library."""

    def __init__(self, mint_url: str, nsec: str, wallet_dir: str):
        self.mint_url = mint_url
        self.nsec = nsec
        self.wallet_dir = wallet_dir

    def redeem(self, token_str: str) -> dict:
        try:
            return asyncio.run(self._redeem(token_str))
        except Exception as exc:  # noqa: BLE001 - report the mint's refusal
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    async def _redeem(self, token_str: str) -> dict:
        wallet = await Wallet.with_db(
            self.mint_url, db=self.wallet_dir, name="settler", unit="sat")
        wallet.private_key = PrivateKey(bytes.fromhex(self.nsec))
        token = deserialize_token_from_string(token_str)
        await receive(wallet, token)
        await wallet.load_proofs(reload=True)
        return {"ok": True, "balance": str(wallet.balance),
                "unit": str(wallet.unit)}


def checkstate(mint_url: str, token_str: str) -> dict:
    token = TokenV4.deserialize(token_str)
    ys = [proof.Y for proof in token.proofs]
    response = httpx.post(f"{mint_url}/v1/checkstate",
                          json={"Ys": ys}, timeout=15.0)
    response.raise_for_status()
    states = response.json().get("states", [])
    return {
        "Ys": len(ys),
        "states": [state.get("state") for state in states],
        "all_spent": all(state.get("state") == "SPENT" for state in states),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("token_file")
    parser.add_argument("--keys-file", required=True)
    parser.add_argument("--seller-pubkey", required=True)
    parser.add_argument("--seller-npub", required=True)
    parser.add_argument("--seller-nsec", required=True)
    parser.add_argument("--mint", default="http://lt-mint:3338")
    parser.add_argument("--buyer-npub", default="npub1testbuyer")
    parser.add_argument("--db-dir", default="/data/settle")
    parser.add_argument("--wallet-dir", default="/data/settler-wallet")
    parser.add_argument("--cap-msat", default="100000")
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
    gate = PaymentGate(journal, exposure, VerifiedJSON(), args.seller_npub,
                       cap_msat=args.cap_msat,
                       settlement_window_secs=3600)
    proofs = proofs_from_result(verified, args.buyer_npub)
    receipts = [gate.accept(proof, "msg1-test") for proof in proofs]
    reserved = [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
                for p in proofs]
    unique_keys = {r.exposure_key for r in receipts}
    outstanding_before = sum(
        (exposure.outstanding(key) for key in unique_keys), Decimal(0))

    redeemer = LocalCashuRedeemer(args.mint, args.seller_nsec,
                                  args.wallet_dir)
    worker = SettlementWorker(journal, exposure, redeemer)
    settlement = worker.settle(receipts, token_str)

    settled = [journal.state(p.mint_url, p.unit, p.keyset_id, p.nullifier)
               for p in proofs]
    outstanding_after = sum(
        (exposure.outstanding(key) for key in unique_keys), Decimal(0))
    replay = None
    try:
        gate.accept(proofs[0], "msg1-test")
    except Exception as exc:  # noqa: BLE001
        replay = type(exc).__name__
    states = checkstate(args.mint, token_str)

    journal.close()
    exposure.close()

    summary = {
        "verify_ok": verified["ok"],
        "proofs": len(proofs),
        "journal_after_accept": reserved,
        "exposure_before_msat": str(outstanding_before),
        "redemption": settlement.redemption,
        "settled": settlement.settled,
        "already_settled": settlement.already_settled,
        "journal_after_settle": settled,
        "exposure_after_msat": str(outstanding_after),
        "replay_after_settle": replay,
        "nut07": states,
    }
    print(json.dumps(summary, indent=2))
    expected = (
        reserved == ["RESERVED"] * len(proofs)
        and settlement.settled == len(proofs)
        and settled == ["SETTLED"] * len(proofs)
        and outstanding_after == Decimal(0)
        and replay in ("AlreadySettled",)
        and states["all_spent"]
    )
    return 0 if expected else 1


if __name__ == "__main__":
    sys.exit(main())
