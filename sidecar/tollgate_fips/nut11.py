"""Strict NUT-11 P2PK admission policy for an offline receiver.

This validates structural conditions only; it does not replace the mint's
DLEQ signature verification or the local spent-nullifier journal. For offline
acceptance require an exact one-of-one lock to this seller's compressed public
key, with no refund, timelock, multisig, grouped signing or unknown extension.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from .journal import keyset_admissible

_COMPRESSED_KEY = re.compile(r"^(?:02|03)[0-9a-fA-F]{64}$")
_ALLOWED_FIELDS = {"data", "nonce", "tags"}
_ALLOWED_TAG_KEYS = {"sigflag", "locktime", "refund", "pubkeys", "n_sigs"}


class OfflineProofRejected(ValueError):
    pass


def is_compressed_secp256k1(key: str) -> bool:
    return bool(isinstance(key, str) and _COMPRESSED_KEY.fullmatch(key))


def _condition_dict(condition: Any) -> dict:
    if isinstance(condition, str):
        try:
            condition = json.loads(condition)
        except (TypeError, ValueError) as exc:
            raise OfflineProofRejected("malformed P2PK JSON") from exc
    if (not isinstance(condition, (list, tuple)) or len(condition) != 2
            or condition[0] != "P2PK" or not isinstance(condition[1], dict)):
        raise OfflineProofRejected("P2PK spending condition required")
    return condition[1]


def check_offline_condition(condition: Any, seller_pubkey: str,
                            final_expiry: Optional[int] = None,
                            settlement_window: int = 3600,
                            now: Optional[float] = None) -> None:
    """Raise on any lock that is not one-way value to this precise seller.

    NUT-11 fields with redeem/refund paths or unknown semantics are rejected
    instead of treated as present-but-harmless. `final_expiry` may be absent;
    if present, the mint/keyset admission deadline must exceed the window.
    """
    if not is_compressed_secp256k1(seller_pubkey):
        raise OfflineProofRejected("seller needs a 33-byte compressed pubkey")
    payload = _condition_dict(condition)
    if set(payload) - _ALLOWED_FIELDS:
        raise OfflineProofRejected("unknown P2PK condition fields")
    if payload.get("data") != seller_pubkey:
        raise OfflineProofRejected("P2PK lock is not this balloon's compressed key")

    tags = payload.get("tags", [])
    if not isinstance(tags, list):
        raise OfflineProofRejected("P2PK tags must be a list")
    for tag in tags:
        if (not isinstance(tag, list) or not tag or not isinstance(tag[0], str)
                or len(tag) < 2):
            raise OfflineProofRejected("malformed P2PK tag")
        key, value = tag[0], tag[1]
        if key not in _ALLOWED_TAG_KEYS:
            raise OfflineProofRejected(f"unknown P2PK extension: {key}")
        if key == "sigflag" and value != "SIG_INPUTS":
            raise OfflineProofRejected("grouped/multisig-witness signing is not allowed")
        if key in {"locktime", "refund", "pubkeys", "n_sigs"}:
            raise OfflineProofRejected(f"P2PK reclaim path not allowed: {key}")

    if not keyset_admissible(final_expiry, settlement_window, now=now):
        raise OfflineProofRejected("keyset expires inside the settlement window")


def require_compressed_lock_key(key: str) -> str:
    """Offer constructor helper: prevent using an x-only npub as a P2PK key."""
    if not is_compressed_secp256k1(key):
        raise OfflineProofRejected("publish a 33-byte compressed public key, not an npub")
    return key.lower()
