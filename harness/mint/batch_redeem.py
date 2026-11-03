#!/usr/bin/env python3
"""Batch settlement: redeem several tokens in one mint swap.

Runs inside the Nutshell image. Each token is verified and accepted into the
vault separately (its own journal rows and exposure), then one swap redeems all
of them. Input fees are linear per input but rounded up per swap, so the batch
should pay less than one swap per token.

The acceptance and settlement are separated by a close/reopen of all databases
to keep the crash-recovery path on the critical path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import verify_token
from cashu.core.base import TokenV4
from cashu.core.crypto.secp import PrivateKey
from cashu.wallet.helpers import deserialize_token_from_string
from cashu.wallet.wallet import Wallet
from gate_token import VerifiedJSON, proofs_from_result

from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.payment import PaymentGate
from tollgate_fips.settlement import SettlementWorker
from tollgate_fips.vault import TokenVault


class LocalBatchRedeemer:
    def __init__(self, mint_url: str, nsec: str, wallet_dir: str):
        self.mint_url = mint_url
        self.nsec = nsec
        self.wallet_dir = wallet_dir

    def redeem(self, token: str) -> dict:
        return self.redeem_many([token])

    def redeem_many(self, tokens) -> dict:
        try:
            return asyncio.run(self._redeem_many(tokens))
        except Exception as exc:  # noqa: BLE001 - report the mint's refusal
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    async def _redeem_many(self, tokens) -> dict:
        wallet = await Wallet.with_db(
            self.mint_url, db=self.wallet_dir, name="batch", unit="sat")
        await wallet.load_mint()
        wallet.private_key = PrivateKey(bytes.fromhex(self.nsec))
        proofs = []
        for token_str in tokens:
            token = deserialize_token_from_string(token_str)
            token_proofs = token.proofs
            await wallet._expand_short_keyset_ids(token_proofs)
            proofs.extend(token_proofs)
        amount_in = sum(proof.amount for proof in proofs)
        keyset = wallet.keysets.get(proofs[0].id) if proofs else None
        fee_ppk = int(getattr(keyset, "input_fee_ppk", 0) or 0)
        kept, _ = await wallet.redeem(proofs)
        await wallet.load_proofs(reload=True)
        amount_out = sum(proof.amount for proof in kept)
        return {
            "ok": True,
            "tokens": len(tokens),
            "inputs": len(proofs),
            "amount_in_sat": amount_in,
            "amount_out_sat": amount_out,
            "fee_sat": amount_in - amount_out,
            "input_fee_ppk": fee_ppk,
        }


def separate_fee_estimate(result, tokens: int) -> int:
    """What the same tokens would cost as one swap each.

    Input fees are linear but rounded up per swap; estimate each swap from the
    batch's input count and the advertised `input_fee_ppk`.
    """
    import math
    if tokens == 0 or not result.redemptions:
        return 0
    batch = result.redemptions[0]
    inputs = int(batch.get("inputs", 0) or 0)
    ppk = int(batch.get("input_fee_ppk", 0) or 0)
    if tokens == 0 or inputs == 0:
        return 0
    per_token_inputs = inputs / tokens
    per_swap = max(1, math.ceil(per_token_inputs * ppk / 1000))
    return per_swap * tokens


def checkstate(mint_url: str, tokens) -> dict:
    ys = []
    for token_str in tokens:
        ys.extend(proof.Y for proof in TokenV4.deserialize(token_str).proofs)
    import httpx
    response = httpx.post(f"{mint_url}/v1/checkstate",
                          json={"Ys": ys}, timeout=20.0)
    response.raise_for_status()
    states = response.json().get("states", [])
    return {
        "Ys": len(ys),
        "all_spent": all(state.get("state") == "SPENT" for state in states),
        "states": [state.get("state") for state in states],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("token_files", nargs="+")
    parser.add_argument("--keys-file", required=True)
    parser.add_argument("--seller-pubkey", required=True)
    parser.add_argument("--seller-npub", required=True)
    parser.add_argument("--seller-nsec", required=True)
    parser.add_argument("--mint", default="http://lt-mint:3338")
    parser.add_argument("--buyer-npub", default="npub1testbuyer")
    parser.add_argument("--db-dir", default="/data/settle-batch")
    parser.add_argument("--wallet-dir", default="/data/batch-wallet")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--cap-msat", default="1000000")
    args = parser.parse_args()

    tokens = [Path(path).read_text().strip().splitlines()[0]
              for path in args.token_files]
    cache = verify_token.fetch_keysets(args.mint, args.keys_file)
    accepted = 0
    amount_in_msat = Decimal(0)
    for token_str in tokens:
        verified = verify_token.verify(token_str, cache, args.seller_pubkey,
                                       args.mint, settlement_window=3600)
        if not verified["ok"]:
            print(json.dumps({"verify_ok": False,
                              "problems": verified["problems"]}, indent=2))
            return 1
        for proof in proofs_from_result(verified, args.buyer_npub):
            amount_in_msat += proof.amount_msat
        accepted += 1

    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    journal = NullifierJournal(str(db_dir / "journal.sqlite3"))
    exposure = ExposureLedger(str(db_dir / "exposure.sqlite3"))
    vault = TokenVault(str(db_dir / "vault.sqlite3"))
    gate = PaymentGate(journal, exposure, VerifiedJSON(), args.seller_npub,
                       cap_msat=args.cap_msat,
                       settlement_window_secs=3600)
    for token_str in tokens:
        verified = verify_token.verify(token_str, cache, args.seller_pubkey,
                                       args.mint, settlement_window=3600)
        for proof in proofs_from_result(verified, args.buyer_npub):
            gate.accept(proof, "msg1-test", vault=vault, token=token_str)

    exposure_key = ExposureKey(args.buyer_npub, args.mint, "sat")
    exposure_before = exposure.outstanding(exposure_key)
    vault_pending_before = len(vault.pending())

    # Crash between acceptance and settlement: reopen everything.
    journal.close()
    exposure.close()
    vault.close()
    journal = NullifierJournal(str(db_dir / "journal.sqlite3"))
    exposure = ExposureLedger(str(db_dir / "exposure.sqlite3"))
    vault = TokenVault(str(db_dir / "vault.sqlite3"))

    worker = SettlementWorker(
        journal, exposure,
        LocalBatchRedeemer(args.mint, args.seller_nsec, args.wallet_dir))
    result = worker.settle_vault_batch(vault, batch_size=args.batch_size)

    states = checkstate(args.mint, tokens)
    vault_pending_after = len(vault.pending())
    exposure_after = exposure.outstanding(exposure_key)
    journal.close()
    exposure.close()
    vault.close()

    summary = {
        "date": time.strftime("%Y-%m-%d"),
        "tokens": accepted,
        "batch_size": args.batch_size,
        "batches": result.batches,
        "settled_rows": result.settled,
        "failed_rows": result.failed,
        "fee_sat_batched": result.fee_sat,
        "fee_sat_separate_estimate": separate_fee_estimate(result, accepted),
        "vault_pending_before": vault_pending_before,
        "vault_pending_after": vault_pending_after,
        "exposure_before_msat": str(exposure_before),
        "exposure_after_msat": str(exposure_after),
        "nut07": states,
        "errors": result.errors,
        "redemptions": result.redemptions,
    }
    print(json.dumps(summary, indent=2))
    expected = (
        result.settled == vault_pending_before and result.failed == 0
        and vault_pending_after == 0
        and exposure_after == Decimal(0)
        and states["all_spent"]
        and result.batches <= 1
    )
    return 0 if expected else 1


if __name__ == "__main__":
    sys.exit(main())
