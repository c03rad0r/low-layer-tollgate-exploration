"""Settlement: redeem accepted proofs, then close the journal and exposure.

`PaymentGate` accepts a proof optimistically: the journal row is RESERVED and
the exposure is outstanding until the mint confirms the value is real. This
module is the step that makes that true:

    redeem the token at the mint
      -> journal.settle()  (RESERVED -> SETTLED)
      -> exposure.release()

If the mint says the token is already spent, the caller reconciles with
`reconcile_spent`, which marks the journal SPENT and releases the exposure so a
double spend does not consume the payer's cap forever.

The redeemer is injected: the sidecar does not depend on a Cashu library, and
the lab runs the redemption inside the Nutshell image.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Protocol

from .exposure import ExposureKey, ExposureLedger
from .journal import AlreadySettled, NullifierJournal, Reservation


class SettlementError(RuntimeError):
    pass


class Redeemer(Protocol):
    def redeem(self, token: str) -> Dict[str, Any]:
        """Spend `token` at the mint. Return `{"ok": bool, ...}`."""
        ...


@dataclass
class VaultSettlementResult:
    settled: int = 0
    failed: int = 0
    tokens: int = 0
    errors: List[str] = None
    redemptions: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.redemptions is None:
            self.redemptions = []


@dataclass
class SettlementResult:
    settled: int
    already_settled: int
    exposure_released_msat: Decimal
    redemption: Dict[str, Any]


class SettlementWorker:
    def __init__(self, journal: NullifierJournal, exposure: ExposureLedger,
                 redeemer: Redeemer):
        self.journal = journal
        self.exposure = exposure
        self.redeemer = redeemer

    def settle(self, receipts: Iterable[Any], token: str) -> SettlementResult:
        """Redeem `token` and settle every receipt it backs.

        Receipts must all come from the same token; the caller is responsible
        for that. Settlement is idempotent: an already-SETTLED row is counted,
        not raised, so a retry after a crash does not fail the payment.
        """
        receipts = list(receipts)
        if not receipts:
            raise SettlementError("no receipts to settle")
        result = self.redeemer.redeem(token)
        if not result.get("ok"):
            raise SettlementError(
                f"redemption failed: {result.get('error') or result}")

        settled = 0
        already = 0
        released = Decimal(0)
        for receipt in receipts:
            try:
                self.journal.settle(receipt.reservation)
                settled += 1
            except AlreadySettled:
                already += 1
            self.exposure.release(receipt.exposure_key,
                                  receipt.proof.amount_msat)
            released += Decimal(str(receipt.proof.amount_msat))
        return SettlementResult(
            settled=settled,
            already_settled=already,
            exposure_released_msat=released,
            redemption=result,
        )

    def reconcile_spent(self, receipts: Iterable[Any],
                        note: str = "double spend") -> int:
        """Mark receipts SPENT after the mint says the token was already used."""
        count = 0
        for receipt in receipts:
            self.journal.mark_spent(receipt.reservation, note=note)
            self.exposure.release(receipt.exposure_key,
                                  receipt.proof.amount_msat)
            count += 1
        return count

    def pending(self, limit: int = 100) -> List[Any]:
        """Journal rows still waiting for settlement."""
        return self.journal.pending(limit=limit)

    def settle_vault(self, vault) -> VaultSettlementResult:
        """Drain pending vault rows: redeem each token, settle its journal rows.

        A failed redemption leaves that token's rows pending and reports the
        error; `reconcile_spent` is the manual path for a token the mint says
        was already used. Rows that are already SETTLED are counted, not raised.
        """
        entries = vault.pending()
        grouped = vault.by_token(entries)
        result = VaultSettlementResult(tokens=len(grouped))
        for token, rows in grouped.items():
            redemption = self.redeemer.redeem(token)
            result.redemptions.append(redemption)
            if not redemption.get("ok"):
                result.failed += len(rows)
                result.errors.append(
                    f"{token[:16]}…: {redemption.get('error') or 'redeem failed'}")
                continue
            for row in rows:
                reservation = Reservation(
                    mint_url=row.mint_url, unit=row.unit,
                    keyset_id=row.keyset_id, nullifier=row.nullifier,
                    amount_msat=row.amount_msat,
                    final_expiry=row.final_expiry,
                    reserved_at=row.created_at,
                )
                try:
                    self.journal.settle(reservation)
                except AlreadySettled:
                    pass
                self.exposure.release(
                    ExposureKey(row.payer_npub, row.mint_url, row.unit),
                    row.amount_msat,
                )
                vault.mark_settled(row.vault_key)
                result.settled += 1
        return result
