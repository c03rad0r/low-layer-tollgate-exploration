import os
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace

from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.settlement import (
    SettlementError,
    SettlementWorker,
)

MINT = "https://mint.test"
UNIT = "sat"
KEYSET = "009a1f293253e41e"
PAYER = "npub1payer"


class FakeRedeemer:
    def __init__(self, ok=True, error=None):
        self.ok = ok
        self.error = error
        self.calls = []

    def redeem(self, token):
        self.calls.append(token)
        if self.ok:
            return {"ok": True, "balance": 49}
        return {"ok": False, "error": self.error or "already spent"}


class SettlementTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = NullifierJournal(os.path.join(self.tmp.name, "j.sqlite3"))
        self.exposure = ExposureLedger(os.path.join(self.tmp.name, "e.sqlite3"))
        self.key = ExposureKey(PAYER, MINT, UNIT)
        self.receipts = []
        for i, amount in enumerate((2, 16, 32)):
            reservation = self.journal.reserve(
                mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                nullifier=f"{i:064x}", amount_msat=Decimal(amount) * 1000,
            )
            self.exposure.reserve(self.key, Decimal(amount) * 1000, 100000)
            self.receipts.append(SimpleNamespace(
                reservation=reservation,
                exposure_key=self.key,
                proof=SimpleNamespace(amount_msat=Decimal(amount) * 1000),
            ))

    def tearDown(self):
        self.journal.close()
        self.exposure.close()
        self.tmp.cleanup()

    def test_settle_closes_all_rows_and_exposure(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        result = worker.settle(self.receipts, "cashuBtoken")
        self.assertEqual(result.settled, 3)
        self.assertEqual(result.already_settled, 0)
        self.assertEqual(result.exposure_released_msat, Decimal(50000))
        for receipt in self.receipts:
            r = receipt.reservation
            self.assertEqual(
                self.journal.state(r.mint_url, r.unit, r.keyset_id, r.nullifier),
                "SETTLED")
        self.assertEqual(self.exposure.outstanding(self.key), Decimal(0))

    def test_failed_redemption_leaves_everything_reserved(self):
        worker = SettlementWorker(self.journal, self.exposure,
                                  FakeRedeemer(ok=False))
        with self.assertRaises(SettlementError):
            worker.settle(self.receipts, "cashuBtoken")
        for receipt in self.receipts:
            r = receipt.reservation
            self.assertEqual(
                self.journal.state(r.mint_url, r.unit, r.keyset_id, r.nullifier),
                "RESERVED")
        self.assertEqual(self.exposure.outstanding(self.key), Decimal(50000))

    def test_retry_after_settle_is_idempotent(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        worker.settle(self.receipts, "cashuBtoken")
        result = worker.settle(self.receipts, "cashuBtoken")
        self.assertEqual(result.settled, 0)
        self.assertEqual(result.already_settled, 3)
        self.assertEqual(self.exposure.outstanding(self.key), Decimal(0))

    def test_reconcile_spent_marks_and_releases(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        count = worker.reconcile_spent(self.receipts)
        self.assertEqual(count, 3)
        for receipt in self.receipts:
            r = receipt.reservation
            self.assertEqual(
                self.journal.state(r.mint_url, r.unit, r.keyset_id, r.nullifier),
                "SPENT")
        self.assertEqual(self.exposure.outstanding(self.key), Decimal(0))

    def test_no_receipts_is_refused(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        with self.assertRaises(SettlementError):
            worker.settle([], "cashuBtoken")

    def test_pending_lists_reserved_rows(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        self.assertEqual(len(worker.pending()), 3)


if __name__ == "__main__":
    unittest.main()
