import os
import tempfile
import unittest
from decimal import Decimal

from tollgate_fips.exposure import (
    ExposureExceeded,
    ExposureKey,
    ExposureLedger,
    UnknownExposure,
)

KEY = ExposureKey("npub1payer", "https://mint.test", "sat")


class ExposureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "exposure.sqlite3")
        self.ledger = ExposureLedger(self.path)

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_reserve_and_release(self):
        self.assertEqual(self.ledger.reserve(KEY, 40, 100), Decimal("40"))
        self.assertEqual(self.ledger.reserve(KEY, 60, 100), Decimal("100"))
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("100"))
        self.assertEqual(self.ledger.release(KEY, 60), Decimal("40"))
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("40"))

    def test_cap_is_enforced(self):
        self.ledger.reserve(KEY, 90, 100)
        with self.assertRaises(ExposureExceeded):
            self.ledger.reserve(KEY, 11, 100)
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("90"))

    def test_cap_of_zero_refuses_everything(self):
        with self.assertRaises(ExposureExceeded):
            self.ledger.reserve(KEY, 1, 0)

    def test_release_clamps_at_zero(self):
        self.ledger.reserve(KEY, 10, 100)
        self.assertEqual(self.ledger.release(KEY, 25), Decimal("0"))
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("0"))

    def test_release_unknown_key_raises(self):
        with self.assertRaises(UnknownExposure):
            self.ledger.release(KEY, 1)

    def test_keys_are_independent(self):
        other_payer = ExposureKey("npub1other", KEY.mint_url, KEY.unit)
        other_mint = ExposureKey(KEY.payer_npub, "https://other.test", KEY.unit)
        other_unit = ExposureKey(KEY.payer_npub, KEY.mint_url, "msat")
        self.ledger.reserve(KEY, 50, 100)
        self.ledger.reserve(other_payer, 50, 100)
        self.ledger.reserve(other_mint, 50, 100)
        self.ledger.reserve(other_unit, 50, 100)
        self.assertEqual(len(self.ledger.rows()), 4)
        self.assertEqual(self.ledger.outstanding(other_payer), Decimal("50"))

    def test_exact_decimal(self):
        self.ledger.reserve(KEY, Decimal("0.001"), Decimal("1"))
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("0.001"))
        self.ledger.release(KEY, Decimal("0.0005"))
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("0.0005"))

    def test_state_survives_reopen(self):
        self.ledger.reserve(KEY, 25, 100)
        self.ledger.close()
        self.ledger = ExposureLedger(self.path)
        self.assertEqual(self.ledger.outstanding(KEY), Decimal("25"))

    def test_second_connection_sees_cap(self):
        other = ExposureLedger(self.path)
        try:
            self.ledger.reserve(KEY, 90, 100)
            with self.assertRaises(ExposureExceeded):
                other.reserve(KEY, 20, 100)
        finally:
            other.close()

    def test_invalid_amounts(self):
        with self.assertRaises(Exception):
            self.ledger.reserve(KEY, 0, 100)
        with self.assertRaises(Exception):
            self.ledger.release(KEY, -1)


if __name__ == "__main__":
    unittest.main()
