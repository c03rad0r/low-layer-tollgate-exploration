import os
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace

from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.vault import TokenVault
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


class FakeBatchRedeemer(FakeRedeemer):
    def __init__(self, ok=True, fee_sat=1):
        super().__init__(ok=ok)
        self.fee_sat = fee_sat
        self.batches = []

    def redeem_many(self, tokens):
        self.batches.append(list(tokens))
        if not self.ok:
            return {"ok": False, "error": "batch refused"}
        return {"ok": True, "tokens": len(tokens), "fee_sat": self.fee_sat}


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

    def test_settle_vault_drains_pending_tokens(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            for receipt in self.receipts:
                r = receipt.reservation
                vault.put(token="cashuBtoken", payer_npub=PAYER,
                          mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                          nullifier=r.nullifier,
                          amount_msat=receipt.proof.amount_msat)
            worker = SettlementWorker(self.journal, self.exposure,
                                      FakeRedeemer())
            result = worker.settle_vault(vault)
            self.assertEqual(result.settled, 3)
            self.assertEqual(result.failed, 0)
            self.assertEqual(vault.pending(), [])
            self.assertEqual(self.exposure.outstanding(self.key), Decimal(0))
        finally:
            vault.close()

    def test_settle_vault_leaves_rows_on_failed_redemption(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            for receipt in self.receipts:
                r = receipt.reservation
                vault.put(token="cashuBtoken", payer_npub=PAYER,
                          mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                          nullifier=r.nullifier,
                          amount_msat=receipt.proof.amount_msat)
            worker = SettlementWorker(self.journal, self.exposure,
                                      FakeRedeemer(ok=False))
            result = worker.settle_vault(vault)
            self.assertEqual(result.settled, 0)
            self.assertEqual(result.failed, 3)
            self.assertEqual(len(vault.pending()), 3)
            self.assertEqual(self.exposure.outstanding(self.key), Decimal(50000))
        finally:
            vault.close()

    def test_batch_drain_settles_a_multi_token_swap(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            for receipt in self.receipts:
                r = receipt.reservation
                vault.put(token="cashuBtoken", payer_npub=PAYER,
                          mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                          nullifier=r.nullifier,
                          amount_msat=receipt.proof.amount_msat)
            worker = SettlementWorker(self.journal, self.exposure,
                                      FakeBatchRedeemer(fee_sat=1))
            result = worker.settle_vault_batch(vault, batch_size=10)
            self.assertEqual(result.settled, 3)
            self.assertEqual(result.batches, 1)
            self.assertEqual(result.fee_sat, 1)
            self.assertEqual(len(worker.redeemer.batches), 1)
            self.assertEqual(vault.pending(), [])
        finally:
            vault.close()

    def test_batch_split_respects_batch_size(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            # Two tokens, one row each.
            for i, nullifier in enumerate(("a" * 64, "b" * 64)):
                reservation = self.journal.reserve(
                    mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                    nullifier=nullifier, amount_msat=Decimal("1"))
                self.exposure.reserve(self.key, Decimal(1000), 100000)
                vault.put(token=f"cashuB{i}", payer_npub=PAYER,
                          mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                          nullifier=nullifier, amount_msat=Decimal("1"))
            worker = SettlementWorker(self.journal, self.exposure,
                                      FakeBatchRedeemer(fee_sat=1))
            result = worker.settle_vault_batch(vault, batch_size=1)
            self.assertEqual(result.batches, 2)
            self.assertEqual(len(worker.redeemer.batches), 2)
        finally:
            vault.close()

    def test_batch_failure_leaves_rows_pending(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            for receipt in self.receipts:
                r = receipt.reservation
                vault.put(token="cashuBtoken", payer_npub=PAYER,
                          mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
                          nullifier=r.nullifier,
                          amount_msat=receipt.proof.amount_msat)
            worker = SettlementWorker(self.journal, self.exposure,
                                      FakeBatchRedeemer(ok=False))
            result = worker.settle_vault_batch(vault, batch_size=10)
            self.assertEqual(result.settled, 0)
            self.assertEqual(result.failed, 3)
            self.assertEqual(len(vault.pending()), 3)
        finally:
            vault.close()

    def test_pending_lists_reserved_rows(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        self.assertEqual(len(worker.pending()), 3)


if __name__ == "__main__":
    unittest.main()
