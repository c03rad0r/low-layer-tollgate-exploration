import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tollgate_fips.account import (
    AccountState,
    IdentityMismatch,
    PrepaidAccount,
    PrepaidAccountStore,
)


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = str(Path(self.tempdir.name) / "accounts.sqlite3")

    def account(self, deadline=7200):
        return PrepaidAccount(npub="npub1a", rate_bytes_per_msat=Decimal(10),
                              issued_at_mono=100,
                              max_session_seconds=deadline,
                              grace_seconds=20,
                              link_id="link-1")

    def test_unpaid_cannot_forward(self):
        acct = self.account()
        self.assertFalse(acct.forwarding_allowed)
        self.assertEqual(acct.charge(100), Decimal(0))

    def test_payment_enables_only_authenticated_link(self):
        acct = self.account()
        acct.top_up(1000)
        acct.link_up("npub1a", "new-link")
        self.assertTrue(acct.forwarding_allowed)
        self.assertEqual(acct.charge(100), Decimal(10))

    def test_usage_survives_dormant_gap(self):
        acct = self.account()
        acct.top_up(1000)
        acct.link_up("npub1a", "link-a")
        acct.charge(100)
        acct.link_down()
        self.assertEqual(acct.state, AccountState.DORMANT)
        self.assertEqual(acct.remaining_msat, Decimal(990))
        self.assertFalse(acct.forwarding_allowed)
        acct.link_up("npub1a", "link-b")
        self.assertEqual(acct.state, AccountState.PAID)
        self.assertEqual(acct.charge(100), Decimal(10))
        self.assertEqual(acct.used_msat, Decimal(20))

    def test_expiry_goes_through_grace(self):
        acct = self.account(deadline=60)
        acct.top_up(1000)
        acct.tick(now=161)
        self.assertEqual(acct.state, AccountState.GRACE)
        self.assertFalse(acct.forwarding_allowed)
        acct.tick(now=182)
        self.assertEqual(acct.state, AccountState.EVICTED)
        self.assertEqual(acct.evicted_reason, "grace expired")

    def test_short_deadline_does_not_grant_after_gap(self):
        acct = self.account(deadline=60)
        acct.top_up(1000)
        acct.link_down()
        self.assertEqual(acct.tick(now=10000), AccountState.DORMANT)
        self.assertFalse(acct.forwarding_allowed)
        self.assertEqual(acct.remaining_msat, Decimal(1000))
        self.assertNotEqual(acct.state, AccountState.PAID)

    def test_long_deadline_survives_gap(self):
        acct = self.account()
        acct.top_up(1000)
        acct.link_down()
        acct.tick(now=4400)
        acct.link_up("npub1a", "link-new")
        self.assertEqual(acct.state, AccountState.PAID)
        self.assertEqual(acct.remaining_msat, Decimal(1000))

    def test_topup_does_not_reset_usage(self):
        acct = self.account()
        acct.top_up(1000)
        acct.link_up("npub1a", "l1")
        acct.charge(10000)
        self.assertEqual(acct.state, AccountState.GRACE)
        acct.top_up(500)
        self.assertTrue(acct.forwarding_allowed)
        self.assertEqual(acct.used_msat, Decimal(1000))
        self.assertEqual(acct.remaining_msat, Decimal(500))

    def test_link_must_match_npub(self):
        acct = self.account()
        with self.assertRaises(IdentityMismatch):
            acct.link_up("npub1other", "x")

    def test_dormant_topup_waits_for_resume(self):
        acct = self.account()
        acct.link_down()
        acct.top_up(100)
        self.assertFalse(acct.forwarding_allowed)
        acct.link_up("npub1a", "l2")
        self.assertTrue(acct.forwarding_allowed)

    def test_evicted_needs_explicit_readmission(self):
        acct = self.account()
        acct.top_up(1000)
        acct.evict("unpaid")
        with self.assertRaises(Exception):
            acct.top_up(100)

    def test_store_persists_exact_balances_and_gap_state(self):
        store = PrepaidAccountStore(self.db_path)
        acct = store.get_or_create("npub1a", Decimal(10))
        acct.top_up(Decimal("1000.25"))
        acct.link_up("npub1a", "old-link")
        acct.charge(33)
        acct.link_down()
        store.save(acct)
        store.close()

        store2 = PrepaidAccountStore(self.db_path)
        resumed = store2.get_or_create("npub1a", Decimal(10))
        self.assertEqual(resumed.state, AccountState.DORMANT)
        self.assertEqual(resumed.credit_msat, Decimal("1000.25"))
        self.assertEqual(resumed.used_msat, Decimal("3.3"))
        self.assertEqual(resumed.remaining_msat, Decimal("996.95"))
        self.assertIsNone(resumed.link_id)
        resumed.link_up("npub1a", "new-link")
        store2.save(resumed)
        store2.close()

    def test_fresh_store_creates_unpaid_account(self):
        store = PrepaidAccountStore(self.db_path)
        self.addCleanup(store.close)
        self.assertEqual(store.get_or_create("npub1b", Decimal(10)).state,
                         AccountState.UNPAID)


if __name__ == "__main__":
    unittest.main()
