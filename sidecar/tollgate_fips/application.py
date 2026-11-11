"""Terminal app-relay request/response handler for authenticated FIPS peers."""

from __future__ import annotations

from dataclasses import replace

from .envelope import (
    EnvelopeError,
    ack,
    decode,
    error_code,
    proof_from_wire,
    reject,
)
from .identity import FipsIdentityResolver
from .relay import RelayError


def _req_id(message: dict) -> str | None:
    req = message.get("req")
    if req is None:
        return None
    if not isinstance(req, str) or len(req) > 64:
        raise EnvelopeError("req must be a short opaque correlation string")
    return req


class RelayApplicationHandler:
    """Resolve FIPS identity anew on each datagram, then apply request policy."""

    def __init__(self, controller, resolver: FipsIdentityResolver):
        self.controller = controller
        self.resolver = resolver

    def handle(self, source_ipv6: str, payload: bytes | str) -> dict:
        try:
            message = decode(payload)
            request_id = _req_id(message)
        except EnvelopeError as exc:
            return reject(None, error_code(exc), str(exc))
        try:
            peer = self.resolver.resolve(source_ipv6)
            kind = message["t"]
            if kind == "pay":
                return self._pay(message, request_id, peer)
            if kind == "frame":
                return self._frame(message, request_id, peer)
            if kind == "link_down":
                self.controller.mark_link_down(peer.npub)
                return ack(request_id, self.controller.account(peer.npub))
            if kind == "tick":
                state = self.controller.tick(peer.npub, message.get("now"))
                return {"t": "status", "v": 1, "req": request_id,
                        "state": state.value}
            if kind == "offer_request":
                return {"t": "offer", "v": 1, "req": request_id,
                        "seller_npub": self.controller.seller_npub,
                        "rate_bytes_per_msat": str(self.controller.rate_bytes_per_msat),
                        "version": 1}
            raise EnvelopeError("request type has no handler")
        except Exception as exc:  # known typed controller/validator failures
            return reject(request_id, error_code(exc), str(exc))

    def _pay(self, message: dict, req: str | None, peer) -> dict:
        proofs_raw = message.get("proofs")
        msg1 = message.get("msg1_ephemeral")
        if not isinstance(msg1, str) or not msg1:
            raise RelayError("msg1_ephemeral is required")
        if not isinstance(proofs_raw, list):
            raise RelayError("proofs must be a list")
        proofs = [replace(proof_from_wire(obj), payer_npub=peer.npub)
                  for obj in proofs_raw]
        account, _ = self.controller.accept_payment(peer.npub, peer.link_id,
                                                   proofs, msg1)
        return ack(req, account)

    def _frame(self, message: dict, req: str | None, peer) -> dict:
        size = message.get("frame_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise EnvelopeError("frame_bytes must be a positive integer")
        outcome = self.controller.forward_frame(peer.npub, peer.link_id, size)
        return {"t": "frame_result", "v": 1, "req": req,
                "allowed": outcome.allowed, "state": outcome.state.value,
                "charged_msat": str(outcome.charged_msat),
                "remaining_msat": str(outcome.remaining_msat)}
