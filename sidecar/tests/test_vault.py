import os
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

    def test_group_by_token(self):
        self.put(nullifier="a" * 64)
        self.put(nullifier="b" * 64)
        entries = self.vault.pending()
        grouped = self.vault.by_token(entries)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(next(iter(grouped.values()))), 2)


if __name__ == "__main__":
    unittest.main()
