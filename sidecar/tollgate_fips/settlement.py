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

from .exposure import ExposureLedger
from .journal import AlreadySettled, NullifierJournal


class SettlementError(RuntimeError):
    pass


class Redeemer(Protocol):
    def redeem(self, token: str) -> Dict[str, Any]:
        """Spend `token` at the mint. Return `{"ok": bool, ...}`."""
        ...


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
