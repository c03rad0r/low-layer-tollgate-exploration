"""Narrow FIPS application-relay controller.

This is an authenticated request-path policy, not an universal mesh firewall.
`accept_payment` verifiably reserves value before credit. `forward_frame` then
allows one account's declared chargeable frames only while that account can pay.
It deliberately leaves transport-wide forwarding and blocking to another layer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

from .account import AccountState, PrepaidAccountStore
from .journal import NullifierJournal
from .payment import PaymentGate, PaymentProof
from .vault import TokenVault


class RelayError(RuntimeError):
    pass


@dataclass(frozen=True)
class ForwardDecision:
    allowed: bool
    state: AccountState
    charged_msat: Decimal
    remaining_msat: Decimal


class AppRelayController:
    """Account-aware relay whose caller authenticates a real FIPS peer/link.

    `gate_verifier` implements the injected mint/DLEQ/P2PK lock verifier.
    A replay cannot reserve the proof again, and hence cannot top up twice.
    A single writer should wrap calls to this controller for a given account.
    """

    def __init__(self, journal: NullifierJournal, exposure, account_store,
                 verifier, seller_npub: str, cap_msat,
                 rate_bytes_per_msat: Decimal, settlement_window_secs: int = 3600):
        self.accounts: PrepaidAccountStore = account_store
        self.verifier = verifier
        self.seller_npub = seller_npub
        self.rate_bytes_per_msat = Decimal(rate_bytes_per_msat)
        self.gate = PaymentGate(journal, exposure, verifier, seller_npub,
                                cap_msat=cap_msat,
                                settlement_window_secs=settlement_window_secs)

    def _bind_link(self, npub: str, link_id: str):
        if not npub or not link_id:
            raise RelayError("an authenticated npub and link_id are required")
        account = self.accounts.get_or_create(npub, self.rate_bytes_per_msat)
        if account.link_id != link_id:
            account.link_down()
            account.link_up(npub, link_id)
        return account

    def accept_payment(self, payer_npub: str, link_id: str,
                       proofs: Iterable[PaymentProof], msg1_ephemeral: str,
                       vault: Optional[TokenVault] = None,
                       token: Optional[str] = None, now: Optional[float] = None):
        """Verify each proof before granting credit to this precise session.

        The caller supplies the FIPS-authenticated identity alongside link id.
        A rejected second proof never consumes an account balance anew, though
        an individually accepted earlier proof remains reserved for settlement.
        """
        account = self._bind_link(payer_npub, link_id)
        proofs = list(proofs)
        if not proofs:
            raise RelayError("at least one verified Cashu proof is required")
        credited = Decimal(0)
        accepted = []
        for proof in proofs:
            if proof.payer_npub != payer_npub:
                raise RelayError("proof and authenticated payer mismatch")
            receipt = self.gate.accept(proof, msg1_ephemeral, now=now,
                                       vault=vault, token=token)
            accepted.append(receipt)
            credited += Decimal(str(proof.amount_msat))
        account.top_up(credited)
        self.accounts.save(account)
        return account, accepted

    def forward_frame(self, payer_npub: str, link_id: str, frame_bytes: int,
                      now: Optional[float] = None) -> ForwardDecision:
        """Decide one whole FMP frame then persist the balance before returning."""
        if frame_bytes <= 0:
            raise RelayError("a positive FMP frame length is required")
        account = self._bind_link(payer_npub, link_id)
        charged = account.charge(frame_bytes, now=now)
        allowed = charged > 0
        self.accounts.save(account)
        return ForwardDecision(allowed=allowed, state=account.state,
                               charged_msat=charged,
                               remaining_msat=account.remaining_msat)

    def mark_link_down(self, npub: str) -> None:
        account = self.accounts.get_or_create(npub, self.rate_bytes_per_msat)
        account.link_down()
        self.accounts.save(account)

    def tick(self, npub: str, now: Optional[float] = None) -> AccountState:
        account = self.accounts.get_or_create(npub, self.rate_bytes_per_msat)
        result = account.tick(now if now is not None else time.monotonic())
        self.accounts.save(account)
        return result

    def account(self, npub: str):
        return self.accounts.get_or_create(npub, self.rate_bytes_per_msat)
