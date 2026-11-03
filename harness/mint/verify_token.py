#!/usr/bin/env python3
"""Verify a Cashu token offline against cached keyset keys.

Runs inside the `cashubtc/nutshell` image, which has the `cashu` library and its
`coincurve` dependency. This is a lab verifier: production would import the
library (or a smaller equivalent) into the seller.

What it checks:

- token parses as TokenV4 and its mint/unit match expectation;
- every proof's DLEQ proof verifies against the keyset public key;
- every proof is unlocked or locked to the expected seller pubkey;
- the locktime leaves room for settlement;
- the proof amounts sum to the token amount.

It does **not** check spentness. That is the journal's job; NUT-07 is the online
cross-check and is deliberately not called here.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from cashu.core.base import TokenV4
from cashu.core.crypto import b_dhke
from cashu.core.crypto.secp import PrivateKey, PublicKey
from cashu.core.nuts import nut10
from cashu.core.p2pk import P2PKSecret, SigFlags, verify_schnorr_signature


def fetch_keysets(mint: str, cache_path: str | None) -> dict:
    if cache_path and Path(cache_path).exists():
        return json.loads(Path(cache_path).read_text())
    keysets_resp = httpx.get(f"{mint}/v1/keysets", timeout=10.0)
    keysets_resp.raise_for_status()
    out = {"mint": mint, "keysets": {}}
    for info in keysets_resp.json()["keysets"]:
        keys_resp = httpx.get(f"{mint}/v1/keys/{info['id']}", timeout=10.0)
        keys_resp.raise_for_status()
        out["keysets"][info["id"]] = {
            "id": info["id"],
            "unit": info.get("unit"),
            "final_expiry": info.get("final_expiry"),
            "input_fee_ppk": info.get("input_fee_ppk"),
            "keys": keys_resp.json()["keysets"][0]["keys"],
        }
    if cache_path:
        Path(cache_path).write_text(json.dumps(out, indent=2) + "\n")
    return out


def find_keyset(cache: dict, short_id: str) -> dict:
    for keyset_id, keyset in cache["keysets"].items():
        if keyset_id.startswith(short_id) or short_id.startswith(keyset_id):
            return keyset
    raise KeyError(f"keyset {short_id} not in cache")


def verify(token_str: str, cache: dict, seller_pubkey: str | None,
           expected_mint: str | None, settlement_window: int) -> dict:
    token = TokenV4.deserialize(token_str)
    now = int(time.time())
    problems = []
    proofs_out = []

    if expected_mint and token.mint.rstrip("/") != expected_mint.rstrip("/"):
        problems.append(f"mint {token.mint} != {expected_mint}")

    total = 0
    for proof in token.proofs:
        total += proof.amount
        keyset = find_keyset(cache, proof.id)
        entry = {
            "amount": proof.amount,
            "keyset_id": proof.id,
            "nullifier": proof.secret,
            "locktime": None,
            "sigflag": None,
            "dleq_valid": False,
            "p2pk_lock_ok": None,
            "witness_ok": None,
        }
        try:
            entry["dleq_valid"] = b_dhke.carol_verify_dleq(
                secret_msg=proof.secret,
                C=PublicKey(bytes.fromhex(proof.C)),
                r=PrivateKey(bytes.fromhex(proof.dleq.r)),
                e=PrivateKey(bytes.fromhex(proof.dleq.e)),
                s=PrivateKey(bytes.fromhex(proof.dleq.s)),
                A=PublicKey(bytes.fromhex(keyset["keys"][str(proof.amount)])),
            )
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            entry["dleq_error"] = str(exc)
        if not entry["dleq_valid"]:
            problems.append(f"proof {proof.amount}: DLEQ invalid")

        try:
            condition = nut10.parse_spending_condition(proof.secret)
        except Exception as exc:  # noqa: BLE001
            condition = None
            entry["condition_error"] = str(exc)

        if isinstance(condition, P2PKSecret):
            entry["locktime"] = condition.locktime
            entry["sigflag"] = condition.sigflag.value
            entry["p2pk_lock_ok"] = (
                seller_pubkey is None or condition.data == seller_pubkey
            )
            if not entry["p2pk_lock_ok"]:
                problems.append(
                    f"proof {proof.amount}: locked to {condition.data}, "
                    f"not {seller_pubkey}"
                )
            if condition.locktime is not None:
                if condition.locktime < now + settlement_window:
                    problems.append(
                        f"proof {proof.amount}: locktime {condition.locktime} "
                        f"leaves less than {settlement_window}s"
                    )
            signatures = proof.p2pksigs if proof.witness else []
            if signatures and seller_pubkey:
                if condition.sigflag is SigFlags.SIG_ALL:
                    entry["witness_ok"] = None  # grouped message, not handled here
                else:
                    entry["witness_ok"] = any(
                        verify_schnorr_signature(
                            proof.secret.encode(),
                            PublicKey(bytes.fromhex(seller_pubkey)),
                            bytes.fromhex(sig),
                        )
                        for sig in signatures
                    )
                    if not entry["witness_ok"]:
                        problems.append(
                            f"proof {proof.amount}: P2PK witness invalid"
                        )
        proofs_out.append(entry)

    if total != token.amount:
        problems.append(f"proof sum {total} != token amount {token.amount}")

    keyset_expiry = sorted(
        {find_keyset(cache, p.id)["final_expiry"] for p in token.proofs},
        key=lambda value: (value is None, value or 0),
    )
    return {
        "ok": not problems,
        "problems": problems,
        "mint": token.mint,
        "unit": token.unit,
        "amount": token.amount,
        "proofs": proofs_out,
        "keyset_final_expiry": keyset_expiry,
        "offline": True,
        "checked_at": now,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("token_file", help="file containing one cashuB... token")
    parser.add_argument("--keys-file", required=True,
                        help="cached keyset JSON; created on first online run")
    parser.add_argument("--seller-pubkey", default=None,
                        help="compressed pubkey the P2PK lock must name")
    parser.add_argument("--mint", default=None, help="expected mint URL")
    parser.add_argument("--offline", action="store_true",
                        help="fail instead of fetching keys if the cache is missing")
    parser.add_argument("--settlement-window", type=int, default=3600)
    args = parser.parse_args()

    token = Path(args.token_file).read_text().strip().splitlines()[0]
    if args.offline and not Path(args.keys_file).exists():
        print(f"error: {args.keys_file} missing and --offline set", file=sys.stderr)
        return 2
    if not Path(args.keys_file).exists() and not args.mint:
        print("error: keys cache missing; pass --mint to fetch it", file=sys.stderr)
        return 2
    mint = args.mint or TokenV4.deserialize(token).mint
    cache = fetch_keysets(mint, args.keys_file)
    result = verify(token, cache, args.seller_pubkey, args.mint,
                    args.settlement_window)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
