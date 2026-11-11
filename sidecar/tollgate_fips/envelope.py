"""Lab-local offer/PAY/ACK/request/reject wire mapping for the app relay.

This is an implementation vocabulary, not a new upstream protocol proposal.
Message correlation ids (`req`) echo requests only. They are not identities and
are never used to decide whether a proof or frame has already been consumed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from .journal import AlreadySettled, AlreadySpent, ReservationInFlight
from .identity import IdentityError
from .nut11 import OfflineProofRejected
from .payment import PaymentProof
from .relay import RelayError


VERSION = 1
WIRE_TYPES = {"pay", "frame", "link_down", "tick", "offer_request"}
APPLICATION_SUFFIX = "tg-app-relay-v1"


class EnvelopeError(ValueError):
    pass


def encode(msg: dict) -> bytes:
    if not isinstance(msg, dict) or msg.get("t") not in WIRE_TYPES:
        raise EnvelopeError("unsupported application request type")
    if msg.get("v", VERSION) != VERSION:
        raise EnvelopeError("unsupported wire version")
    return (json.dumps(msg, separators=(",", ":"), sort_keys=True) + "\n").encode()


def decode(data: bytes | str) -> dict:
    if isinstance(data, str):
        data = data.encode()
    if len(data) > 65536:
        raise EnvelopeError("request exceeds bounded size")
    try:
        msg = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvelopeError("request is not valid UTF-8 JSON") from exc
    if not isinstance(msg, dict):
        raise EnvelopeError("request must be a JSON object")
    if msg.get("t") not in WIRE_TYPES:
        raise EnvelopeError("unrecognized request type")
    if msg.get("v", VERSION) != VERSION:
        raise EnvelopeError("unsupported request version")
    return msg


def proof_from_wire(obj: dict) -> PaymentProof:
    if not isinstance(obj, dict):
        raise EnvelopeError("proof must be an object")
    required = {"mint", "unit", "keyset", "secret", "amount_msat", "condition"}
    if set(obj) != required:
        raise EnvelopeError("proof must have exactly the minimal proof fields")
    if not obj["keyset"]:
        raise EnvelopeError("unknown keyset id")
    amount = Decimal(str(obj["amount_msat"]))
    if amount <= 0:
        raise EnvelopeError("proof amount must be positive")
    return PaymentProof(mint_url=obj["mint"], unit=obj["unit"],
                        keyset_id=obj["keyset"], nullifier=obj["secret"],
                        amount_msat=amount, payer_npub="", final_expiry=obj.get("final_expiry"),
                        token=obj["condition"])


def ack(request_id: Optional[str], account) -> dict:
    return {"t": "ack", "v": VERSION, "req": request_id,
            "state": account.state.value,
            "remaining_msat": str(account.remaining_msat)}


def reject(request_id: Optional[str], code: str, message: str) -> dict:
    return {"t": "nack", "v": VERSION, "req": request_id,
            "code": code, "message": message}


def error_code(exc: Exception) -> str:
    if isinstance(exc, ReservationInFlight):
        return "reservation_in_flight"
    if isinstance(exc, AlreadySpent):
        return "already_spent"
    if isinstance(exc, AlreadySettled):
        return "already_settled"
    if isinstance(exc, IdentityError):
        return "unknown_fips_peer"
    if isinstance(exc, OfflineProofRejected):
        return "invalid_offline_condition"
    if isinstance(exc, RelayError):
        return "relay_rejected"
    if isinstance(exc, EnvelopeError):
        return "invalid_envelope"
    return "payment_rejected"
