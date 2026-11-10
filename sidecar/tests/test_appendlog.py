import json
import struct
import tempfile
import unittest
import tempfile
import unittest
import zlib
from pathlib import Path

from tollgate_fips.appendlog import (
    HEADER,
    MAGIC,
    STATES,
    VERSION,
    CorruptJournal,
    CrcJournal,
)
from tollgate_fips.journal import AlreadySettled, AlreadySpent, ReservationInFlight


class CrcJournalTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db = str(Path(self.tempdir.name) / "journal.fjnl")
        # Tune the sample below so its record fits the on-wire size bound.

    def reserve(self, journal, nullifier="proof-1", amount="10000", keyset="k1"):
        return journal.reserve(mint_url="http://mint", unit="sat",
                               keyset_id=keyset, nullifier=nullifier,
                               amount_msat=amount, final_expiry=None,
                               now=100)

    def test_reserve_then_reopen_refuses_replay(self):
        journal = CrcJournal(self.db)
        self.reserve(journal)
        with self.assertRaises(ReservationInFlight):
            self.reserve(journal)
        journal2 = CrcJournal(self.db)
        self.assertEqual(journal2.state("http://mint", "sat", "k1", "proof-1"),
                         "RESERVED") 
        with self.assertRaises(ReservationInFlight):
            self.reserve(journal2)
        self.assertEqual(len(journal2.pending()), 1)

    def test_settle_rejects_replay_after_reopen(self):
        journal = CrcJournal(self.db)
        self.reserve(journal)
        journal.settle("http://mint", "sat", "k1", "proof-1")
        journal2 = CrcJournal(self.db)
        self.assertEqual(journal2.state("http://mint", "sat", "k1", "proof-1"), "SETTLED")
        with self.assertRaises(AlreadySettled):
            self.reserve(journal2)

    def test_spent_rejects_reissue(self):
        journal = CrcJournal(self.db)
        self.reserve(journal)
        journal.mark_spent(("http://mint", "sat", "k1", "proof-1"))
        with self.assertRaises(AlreadySpent):
            self.reserve(CrcJournal(self.db))

    def test_recovery_treats_stale_reservation_as_spent(self):
        self.reserve(CrcJournal(self.db))
        reopened = CrcJournal(self.db, recover_at_open=True)
        self.assertEqual(reopened.state("http://mint", "sat", "k1", "proof-1"), "SPENT")
        with self.assertRaises(AlreadySpent):
            self.reserve(reopened)

    def _bytes_for_state(self, state_name, nullifier="proof-1"):
        state_id = STATES[state_name]
        payload = json.dumps({"mint_url": "http://mint", "unit": "sat",
                              "keyset_id": "k1", "nullifier": nullifier,
                              "amount_msat": "10000", "final_expiry": None,
                              "at": 100, "state": state_name},
                             sort_keys=True, separators=(",", ":")).encode()
        blob = HEADER.pack(MAGIC, VERSION, state_id, len(payload)) + payload
        return blob + struct.pack("<I", zlib.crc32(payload) & 0xFFFFFFFF)

    def test_torn_tail_is_discarded_not_credited(self):
        complete = self._bytes_for_state("RESERVED")
        Path(self.db).write_bytes(complete[:-1])
        journal = CrcJournal(self.db)
        self.assertEqual(journal.pending(), [])
        # An uncommitted reservation is not a replay: the payer may retry.
        self.reserve(journal)
        self.assertEqual(len(journal.pending()), 1)

    def test_truncated_compact_log_keeps_committed_prefix(self):
        Path(self.db).write_bytes(self._bytes_for_state("RESERVED")
                                  + self._bytes_for_state("SETTLED")[:4])
        journal = CrcJournal(self.db)
        self.assertEqual(len(journal.pending()), 1)
        self.assertEqual(len(journal.records()), 1)
        self.assertFalse(Path(self.db).read_bytes().endswith(b"FJNL"))

    def test_every_truncation_offset_is_recoverable(self):
        blob = self._bytes_for_state("RESERVED", "one") + self._bytes_for_state("RESERVED", "two")
        for cut in range(len(blob) + 1):
            path = Path(self.tempdir.name) / f"cut-{cut}.fjnl"
            path.write_bytes(blob[:cut])
            journal = CrcJournal(str(path))
            states = [r["nullifier"] for r in journal.pending()]
            self.assertIn(states, (["one", "two"], ["one"], []))

    def test_corrupt_record_fails_closed(self):
        blob = bytearray(self._bytes_for_state("RESERVED"))
        blob[-2] ^= 1
        Path(self.db).write_bytes(blob)
        with self.assertRaises(CorruptJournal):
            CrcJournal(self.db)

    def test_wrong_magic_fails_closed(self):
        Path(self.db).write_bytes(b"NOTMAGIC" + b"\x00" * 100)
        with self.assertRaises(CorruptJournal):
            CrcJournal(self.db)

    def test_compaction_keeps_latest_state_per_key(self):
        journal = CrcJournal(self.db)
        self.reserve(journal, "one")
        self.reserve(journal, "two")
        journal.settle("http://mint", "sat", "k1", "one")
        self.assertEqual(len(journal.records()), 3)
        journal2 = CrcJournal(self.db)
        self.assertEqual(len(journal2.records()), 2)
        self.assertEqual(journal2.pending()[0]["nullifier"], "two")
        with self.assertRaises(AlreadySettled):
            self.reserve(journal2, "one")

    def test_settled_reservation_is_not_pending_before_compaction(self):
        journal = CrcJournal(self.db)
        self.reserve(journal, "one")
        journal.settle("http://mint", "sat", "k1", "one")
        self.assertEqual(journal.pending(), [])

    def test_empty_log_is_clean(self):
        journal = CrcJournal(self.db)
        self.assertEqual(journal.records(), [])
        self.assertEqual(journal.pending(), [])

    def test_non_positive_amount_is_rejected(self):
        for amount in ("0", "-1", "not-a-number"):
            journal = CrcJournal(self.db)
            with self.subTest(amount=amount):
                with self.assertRaises(CorruptJournal):
                    self.reserve(journal, amount=amount)

    def test_shape_extra_field_is_rejected(self):
        payload = {"mint_url": "http://mint", "unit": "sat", "keyset_id": "k1",
                   "nullifier": "p", "amount_msat": "1", "state": "RESERVED",
                   "unknown_future_flag": "yes"}
        blob = json.dumps(payload).encode()
        Path(self.db).write_bytes(HEADER.pack(MAGIC, VERSION, STATES["RESERVED"], len(blob)) + blob)
        with Path(self.db).open("ab") as handle:
            handle.write(struct.pack("<I", zlib.crc32(blob) & 0xFFFFFFFF))
        Path(self.db).write_bytes(blob)
        with self.assertRaises(CorruptJournal):
            CrcJournal(self.db)


if __name__ == "__main__":
    unittest.main()
