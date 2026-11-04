import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal

from tollgate_fips.vault import TokenVault, vault_key

MINT = "https://mint.test"
UNIT = "sat"
KEYSET = "009a1f293253e41e"
NULLIFIER = "a" * 64
PAYER = "npub1payer"


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "vault.sqlite3")
        self.vault = TokenVault(self.path)

    def tearDown(self):
        self.vault.close()
        self.tmp.cleanup()

    def put(self, nullifier=NULLIFIER, amount="1.5", token="cashuBtoken"):
        return self.vault.put(
            token=token, payer_npub=PAYER, mint_url=MINT, unit=UNIT,
            keyset_id=KEYSET, nullifier=nullifier, amount_msat=Decimal(amount),
            final_expiry=2_000_000_000, now=100.0,
        )

    def test_put_and_pending(self):
        entry = self.put()
        pending = self.vault.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].vault_key, entry.vault_key)
        self.assertEqual(pending[0].amount_msat, Decimal("1.5"))
        self.assertEqual(pending[0].reservation_key,
                         (MINT, UNIT, KEYSET, NULLIFIER))

    def test_mark_settled_removes_from_pending(self):
        entry = self.put()
        self.vault.mark_settled(entry.vault_key, now=101.0)
        self.assertEqual(self.vault.pending(), [])
        self.assertIsNotNone(self.vault.get(entry.vault_key))

    def test_remove_deletes_the_token(self):
        entry = self.put()
        self.vault.remove(entry.vault_key)
        self.assertIsNone(self.vault.get(entry.vault_key))

    def test_state_survives_reopen(self):
        entry = self.put()
        self.vault.close()
        self.vault = TokenVault(self.path)
        self.assertEqual(self.vault.get(entry.vault_key).token, "cashuBtoken")

    def test_key_is_the_nullifier_tuple(self):
        self.put()
        self.put(nullifier="b" * 64, token="cashuBother")
        self.assertEqual(len(self.vault.pending()), 2)
        self.assertEqual(
            vault_key(MINT, UNIT, KEYSET, NULLIFIER),
            self.vault.pending()[0].vault_key,
        )

    def test_attempts_and_dead_letter_exclude_from_pending(self):
        entry = self.put()
        counts = self.vault.record_attempts([entry.vault_key], now=101.0)
        self.assertEqual(counts[entry.vault_key], 1)
        self.assertEqual(self.vault.pending()[0].attempts, 1)
        self.assertEqual(self.vault.pending()[0].last_attempt_at, 101.0)

        self.assertEqual(
            self.vault.mark_dead_letter([entry.vault_key], now=102.0), 1)
        self.assertEqual(self.vault.pending(), [])
        dead = self.vault.dead_lettered()
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].dead_lettered_at, 102.0)

        self.assertTrue(self.vault.requeue(entry.vault_key))
        pending = self.vault.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].attempts, 0)
        self.assertIsNone(pending[0].last_attempt_at)
        self.assertIsNone(pending[0].dead_lettered_at)
        self.assertEqual(self.vault.dead_lettered(), [])

    def test_attempts_do_not_resurrect_settled_rows(self):
        entry = self.put()
        self.vault.mark_settled(entry.vault_key, now=101.0)
        counts = self.vault.record_attempts([entry.vault_key], now=102.0)
        self.assertEqual(counts[entry.vault_key], 0)
        self.assertTrue(self.vault.pending() == [])
        self.assertTrue(self.vault.dead_lettered() == [])

    def test_counts_splits_pending_dead_and_settled(self):
        first = self.put(nullifier="a" * 64, token="cashuBa")
        second = self.put(nullifier="b" * 64, token="cashuBb")
        third = self.put(nullifier="c" * 64, token="cashuBc")
        self.vault.mark_settled(first.vault_key, now=101.0)
        self.vault.mark_dead_letter([second.vault_key], now=102.0)
        self.assertEqual(self.vault.counts(),
                         {"pending": 1, "dead_lettered": 1, "settled": 1})
        self.assertEqual(third.vault_key, self.vault.pending()[0].vault_key)

    def test_old_schema_is_migrated_in_place(self):
        old_path = os.path.join(self.tmp.name, "old.sqlite3")
        key = vault_key(MINT, UNIT, KEYSET, NULLIFIER)
        con = sqlite3.connect(old_path)
        con.executescript("""
            CREATE TABLE token_vault (
                vault_key TEXT PRIMARY KEY, token TEXT NOT NULL,
                payer_npub TEXT NOT NULL, mint_url TEXT NOT NULL,
                unit TEXT NOT NULL, keyset_id TEXT NOT NULL,
                nullifier TEXT NOT NULL, amount_msat TEXT NOT NULL,
                final_expiry INTEGER, created_at REAL NOT NULL,
                settled_at REAL
            );
        """)
        con.execute(
            "INSERT INTO token_vault VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
            (key, "cashuBold", PAYER, MINT, UNIT, KEYSET, NULLIFIER,
             "1500", None, 100.0))
        con.commit()
        con.close()

        migrated = TokenVault(old_path)
        try:
            entry = migrated.get(key)
            self.assertEqual(entry.token, "cashuBold")
            self.assertEqual(entry.attempts, 0)
            self.assertIsNone(entry.dead_lettered_at)
            migrated.record_attempts([key], now=101.0)
            self.assertEqual(migrated.get(key).attempts, 1)
        finally:
            migrated.close()

    def test_group_by_token(self):
        self.put(nullifier="a" * 64)
        self.put(nullifier="b" * 64)
        entries = self.vault.pending()
        grouped = self.vault.by_token(entries)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(next(iter(grouped.values()))), 2)


if __name__ == "__main__":
    unittest.main()
