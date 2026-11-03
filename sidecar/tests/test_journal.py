import os
import tempfile
import unittest
from decimal import Decimal

from tollgate_fips.journal import (
    AlreadySettled,
    AlreadySpent,
    NullifierJournal,
    ReservationInFlight,
    keyset_admissible,
)

MINT = "https://mint.test"
UNIT = "sat"
KEYSET = "009a1f293253e41e"
NULLIFIER = "a" * 64


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "journal.sqlite3")
        self.j = NullifierJournal(self.path)

    def tearDown(self):
        self.j.close()
        self.tmp.cleanup()

    def reserve(self, **kwargs):
        defaults = dict(
            mint_url=MINT, unit=UNIT, keyset_id=KEYSET, nullifier=NULLIFIER,
            amount_msat=Decimal("1.5"), final_expiry=2_000_000_000, now=100.0,
        )
        defaults.update(kwargs)
        return self.j.reserve(**defaults)

    def test_reserve_then_settle(self):
        reservation = self.reserve()
        self.assertEqual(reservation.amount_msat, Decimal("1.5"))
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "RESERVED")
        self.j.settle(reservation, now=101.0)
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "SETTLED")

    def test_duplicate_reserved_is_refused(self):
        self.reserve()
        with self.assertRaises(ReservationInFlight):
            self.reserve()

    def test_settled_replay_is_refused(self):
        reservation = self.reserve()
        self.j.settle(reservation)
        with self.assertRaises(AlreadySettled):
            self.reserve()

    def test_spent_replay_is_refused(self):
        reservation = self.reserve()
        self.j.mark_spent(reservation, note="double spend")
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "SPENT")
        with self.assertRaises(AlreadySpent):
            self.reserve()

    def test_mark_spent_from_settled(self):
        reservation = self.reserve()
        self.j.settle(reservation)
        self.j.mark_spent(reservation, note="late double spend")
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "SPENT")

    def test_state_survives_reopen(self):
        reservation = self.reserve()
        self.j.close()
        self.j = NullifierJournal(self.path)
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "RESERVED")
        self.j.settle(reservation)
        self.j.close()
        self.j = NullifierJournal(self.path)
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "SETTLED")

    def test_second_connection_sees_the_reservation(self):
        other = NullifierJournal(self.path)
        try:
            self.reserve()
            with self.assertRaises(ReservationInFlight):
                other.reserve(MINT, UNIT, KEYSET, NULLIFIER, Decimal("1.5"),
                              now=100.0)
        finally:
            other.close()

    def test_keyset_is_part_of_the_key(self):
        self.reserve()
        other = self.reserve(keyset_id="00deadbeef")
        self.assertEqual(other.keyset_id, "00deadbeef")
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "RESERVED")

    def test_mint_and_unit_are_part_of_the_key(self):
        self.reserve()
        self.reserve(mint_url="https://other.test")
        self.reserve(unit="msat")
        self.assertEqual(len(self.j.rows()), 3)

    def test_amount_is_exact(self):
        reservation = self.reserve(amount_msat=Decimal("0.001"))
        self.assertEqual(reservation.amount_msat, Decimal("0.001"))
        row = self.j.pending()[0]
        self.assertEqual(row["amount_msat"], "0.001")

    def test_recover_stale_reservations(self):
        self.reserve(now=100.0)
        recovered = self.j.recover_stale_reservations(older_than_seconds=10,
                                                      now=200.0)
        self.assertEqual(recovered, 1)
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "SPENT")
        with self.assertRaises(AlreadySpent):
            self.reserve(now=201.0)

    def test_recover_leaves_fresh_reservations(self):
        self.reserve(now=100.0)
        recovered = self.j.recover_stale_reservations(older_than_seconds=100,
                                                      now=150.0)
        self.assertEqual(recovered, 0)
        self.assertEqual(self.j.state(MINT, UNIT, KEYSET, NULLIFIER), "RESERVED")

    def test_keyset_admissible(self):
        self.assertTrue(keyset_admissible(None, 100, now=1_000))
        self.assertTrue(keyset_admissible(1_200, 100, now=1_000))
        self.assertFalse(keyset_admissible(1_050, 100, now=1_000))
        self.assertFalse(keyset_admissible(1_000, 100, now=1_000))


if __name__ == "__main__":
    unittest.main()
