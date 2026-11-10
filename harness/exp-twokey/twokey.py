#!/usr/bin/env python3
"""E-TWOKEY: two acceptors, one token, one shared P2PK key.

Phases are separate so the mint can be stopped between key caching and
acceptance:

  fetch   cache the mint keys (online)
  accept  verify offline and accept on S1 and S2 (mint may be down)
  redeem  redeem from both acceptors with the same seller key
  diffkey verify the same token against a different seller key
  sync    show whether S1's journal would have refused S2's acceptance
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "/mint")
sys.path.insert(0, "/sidecar")

import httpx
import verify_token
from cashu.core.crypto.secp import PrivateKey
from cashu.wallet.helpers import deserialize_token_from_string, receive
from cashu.wallet.wallet import Wallet
from gate_token import VerifiedJSON, proofs_from_result

from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.payment import PaymentGate


def verify(path: Path, keys: Path, seller_pubkey: str, mint: str) -> dict:
    token = path.read_text().strip().splitlines()[0]
    cache = verify_token.fetch_keysets(mint, str(keys))
    return verify_token.verify(token, cache, seller_pubkey, mint,
                               settlement_window=3600)


def gate(db_dir: Path, seller_pubkey: str) -> tuple:
    db_dir.mkdir(parents=True, exist_ok=True)
    journal = NullifierJournal(str(db_dir / "journal.sqlite3"))
    exposure = ExposureLedger(str(db_dir / "exposure.sqlite3"))
    return journal, exposure, PaymentGate(
        journal, exposure, VerifiedJSON(), "npub1testseller",
        cap_msat=100000, settlement_window_secs=3600)


def do_accept(args) -> dict:
    verified = verify(Path(args.token), Path(args.keys), args.seller_pubkey,
                      args.mint)
    out = {"verify_ok": verified["ok"], "problems": verified["problems"],
           "proofs": len(verified.get("proofs", []))}
    if not verified["ok"]:
        return out
    for name in ("s1", "s2"):
        journal, exposure, g = gate(Path(args.db_dir) / name, args.seller_pubkey)
        proofs = proofs_from_result(verified, "npub1payer")
        states = []
        for proof in proofs:
            try:
                g.accept(proof, "msg1-test", now=verified["checked_at"])
                states.append("ACCEPTED")
            except Exception as exc:  # noqa: BLE001
                states.append(type(exc).__name__)
        out[name] = {
            "states": states,
            "journal": [journal.state(p.mint_url, p.unit, p.keyset_id,
                                      p.nullifier) for p in proofs],
            "exposure": str(exposure.outstanding(
                ExposureKey("npub1payer", verified["mint"],
                            verified.get("unit", "sat")))),
        }
        journal.close(); exposure.close()
    return out


async def _redeem(mint: str, nsec: str, wallet_dir: str, token: str) -> dict:
    wallet = await Wallet.with_db(mint, db=wallet_dir, name="settler",
                                  unit="sat")
    wallet.private_key = PrivateKey(bytes.fromhex(nsec))
    token_obj = deserialize_token_from_string(token)
    await receive(wallet, token_obj)
    await wallet.load_proofs(reload=True)
    return {"ok": True, "balance": str(wallet.balance)}


def do_redeem(args) -> dict:
    token = Path(args.token).read_text().strip().splitlines()[0]
    out = {}
    for name in ("s1", "s2"):
        wallet_dir = str(Path(args.db_dir) / name / "wallet")
        try:
            out[name] = asyncio.run(_redeem(args.mint, args.seller_nsec,
                                            wallet_dir, token))
        except Exception as exc:  # noqa: BLE001
            out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("phase", choices=["fetch", "accept", "redeem", "diffkey",
                                     "sync"])
    p.add_argument("--token", required=True)
    p.add_argument("--keys", required=True)
    p.add_argument("--db-dir", default="/data/twokey")
    p.add_argument("--seller-pubkey", required=True)
    p.add_argument("--seller-nsec", default="")
    p.add_argument("--other-pubkey", default="")
    p.add_argument("--mint", default="http://lt-mint:3338")
    args = p.parse_args()

    if args.phase == "fetch":
        cache = verify_token.fetch_keysets(args.mint, args.keys)
        print(json.dumps({"keysets": list(cache["keysets"]),
                          "cached": args.keys}))
        return 0
    if args.phase == "accept":
        print(json.dumps(do_accept(args), indent=2))
        return 0
    if args.phase == "redeem":
        print(json.dumps(do_redeem(args), indent=2))
        return 0
    if args.phase == "diffkey":
        verified = verify(Path(args.token), Path(args.keys),
                          args.other_pubkey, args.mint)
        print(json.dumps({
            "verify_ok": verified["ok"],
            "problems": verified["problems"],
            "p2pk_lock_ok": [p.get("p2pk_lock_ok")
                             for p in verified.get("proofs", [])],
        }, indent=2))
        return 0
    if args.phase == "sync":
        token = Path(args.token).read_text().strip().splitlines()[0]
        cache = verify_token.fetch_keysets(args.mint, str(args.keys))
        verified = verify_token.verify(token, cache, args.seller_pubkey,
                                       args.mint, 3600)
        s1 = NullifierJournal(str(Path(args.db_dir) / "s1" / "journal.sqlite3"))
        s2 = NullifierJournal(str(Path(args.db_dir) / "s2" / "journal.sqlite3"))
        rows = []
        for item in verified["proofs"]:
            rows.append({
                "nullifier": item["nullifier"][:16] + "...",
                "s1": s1.state(verified["mint"], verified.get("unit", "sat"),
                               item["keyset_id"], item["nullifier"]),
                "s2_would_reject": s1.state(
                    verified["mint"], verified.get("unit", "sat"),
                    item["keyset_id"], item["nullifier"]) is not None,
            })
        s1.close(); s2.close()
        print(json.dumps(rows, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
