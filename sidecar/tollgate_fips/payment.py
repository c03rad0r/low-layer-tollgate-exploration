"""Payment acceptance: verifier -> exposure -> journal, in that order.

The verifier is injected. In production it checks the Cashu proof (mint
signature/DLEQ, NUT-11 P2PK lock to the seller) and the preamble binding to the
FIPS msg1 ephemeral. In tests it is a stub, so the ordering and failure paths
are exercised without a mint.

The gate does not verify money itself, and it does not settle. It makes the
acceptance decision and records it durably.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Protocol

from .exposure import ExposureKey, ExposureLedger
from .journal import NullifierJournal, Reservation, keyset_admissible
from .vault import TokenVault, vault_key


class PaymentError(RuntimeError):
    pass


class VerificationFailed(PaymentError):
    pass


class ProofRejected(PaymentError):
    pass


@dataclass(frozen=True)
class PaymentProof:
    mint_url: str
    unit: str
    keyset_id: str
    nullifier: str
    amount_msat: Decimal
    payer_npub: str
    final_expiry: Optional[int] = None
    token: Any = None


@dataclass(frozen=True)
class Receipt:
    proof: PaymentProof
    reservation: Reservation
    exposure_key: ExposureKey


class Verifier(Protocol):
    def verify(self, proof: PaymentProof, seller_npub: str,
               msg1_ephemeral: str) -> bool:
        ...


class PaymentGate:
    def __init__(self, journal: NullifierJournal, exposure: ExposureLedger,
                 verifier: Verifier, seller_npub: str, cap_msat,
                 settlement_window_secs: int = 3600):
        self.journal = journal
        self.exposure = exposure
        self.verifier = verifier
        self.seller_npub = seller_npub
        self.cap_msat = Decimal(str(cap_msat))
        self.settlement_window_secs = settlement_window_secs

    def accept(self, proof: PaymentProof, msg1_ephemeral: str,
               now: Optional[float] = None, vault: Optional[TokenVault] = None,
               token: Optional[str] = None) -> Receipt:
        """Verify, reserve exposure and the nullifier, and optionally vault the
        bearer token first so a crash cannot lose the only thing that settles
        the payment."""
        amount = Decimal(str(proof.amount_msat))
        if amount <= 0:
            raise PaymentError("amount must be positive")
        if not proof.payer_npub:
            raise PaymentError("payer npub is required")
        if not keyset_admissible(proof.final_expiry,
                                 self.settlement_window_secs, now):
            raise ProofRejected(
                "keyset expires inside the settlement window; refund it instead"
            )
        if not self.verifier.verify(proof, self.seller_npub, msg1_ephemeral):
            raise VerificationFailed("proof did not verify")

        key = ExposureKey(proof.payer_npub, proof.mint_url, proof.unit)
        self.exposure.reserve(key, amount, self.cap_msat)

        # Persist the token before the journal row commits. A crash in between
        # leaves an orphan vault row (recoverable); the reverse order would
        # leave a reserved nullifier with no token (unsettleable).
        vault_key_value = None
        created_vault_row = False
        if vault is not None:
            if not token:
                self.exposure.release(key, amount)
                raise PaymentError("token is required when a vault is configured")
            vault_key_value = vault_key(
                proof.mint_url, proof.unit, proof.keyset_id, proof.nullifier)
            if vault.get(vault_key_value) is None:
                vault.put(
                    token=token, payer_npub=proof.payer_npub,
                    mint_url=proof.mint_url, unit=proof.unit,
                    keyset_id=proof.keyset_id, nullifier=proof.nullifier,
                    amount_msat=amount, final_expiry=proof.final_expiry,
                )
                created_vault_row = True

        try:
            reservation = self.journal.reserve(
                mint_url=proof.mint_url,
                unit=proof.unit,
                keyset_id=proof.keyset_id,
                nullifier=proof.nullifier,
                amount_msat=amount,
                final_expiry=proof.final_expiry,
            )
        except Exception:
            # The journal refused (replay/in-flight). Release the exposure we
            # just took so a refused proof does not consume the payer's cap,
            # and drop the vault row only if this call created it.
            self.exposure.release(key, amount)
            if created_vault_row and vault_key_value is not None:
                vault.remove(vault_key_value)
            raise
        return Receipt(proof=proof, reservation=reservation, exposure_key=key)

    def settle(self, receipt: Receipt) -> None:
        self.journal.settle(receipt.reservation)
        self.exposure.release(receipt.exposure_key, receipt.proof.amount_msat)

    def reject(self, receipt: Receipt, note: str = "double spend") -> None:
        self.journal.mark_spent(receipt.reservation, note=note)
        self.exposure.release(receipt.exposure_key, receipt.proof.amount_msat)
