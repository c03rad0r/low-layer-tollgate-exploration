import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tollgate_fips.appendlog import CrcNullifierJournal
from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import AlreadySpent, ReservationInFlight
from tollgate_fips.nut11 import check_offline_condition
from tollgate_fips.account import AccountState, PrepaidAccountStore
from tollgate_fips.payment import PaymentProof
from tollgate_fips.relay import AppRelayController, RelayError

SELLER_KEY = "02" + "ab" * 32


def valid_condition():
    return ["P2PK", {"data": SELLER_KEY, "nonce": "00" * 16,
                      "tags": [["sigflag", "SIG_INPUTS"]]}]


class Verifier:
    """Lab verifier: structural lock only; real DLEQ covered by mint tests."""

    def verify(self, proof, seller_npub, msg1_ephemeral):
        if isinstance(proof.token, str) and proof.token == "bad-dleq":
            return False
        check_offline_condition(proof.token, SELLER_KEY,
                                proof.final_expiry, now=proof.final_expiry)
        return True


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.controller = self.make_controller()

    def make_controller(self):
        journal = CrcNullifierJournal(str(self.root / "proofs.fjnl"))
        exposure = ExposureLedger(str(self.root / "exposure.sqlite3"))
        accounts = PrepaidAccountStore(str(self.root / "accounts.sqlite3"))
        store = {"journal": journal, "exposure": exposure, "accounts": accounts}
        self.addCleanup(lambda: [x.close() for x in store.values() if hasattr(x, "close")])
        return AppRelayController(journal, exposure, accounts, Verifier(),
                                  "npub1seller", cap_msat=100000,
                                  rate_bytes_per_msat=Decimal(10))

    def proof(self, nullifier: str, amount: int = 1000,
              payer: str = "npub1a", final_expiry=None):
        return PaymentProof(mint_url="http://mint", unit="sat",
                            keyset_id="k1", nullifier=nullifier,
                            amount_msat=Decimal(amount), payer_npub=payer,
                            final_expiry=final_expiry, token=valid_condition())

    def test_valid_payment_enables_account_and_forwards(self):
        account, receipts = self.controller.accept_payment(
            "npub1a", "l1", [self.proof("p1")], "msg1a")
        self.assertEqual(account.state, AccountState.PAID)
        self.assertEqual(account.remaining_msat, Decimal(1000))
        before = self.controller.forward_frame("npub1a", "l1", 100)
        self.assertTrue(before.allowed)
        self.assertEqual(before.charged_msat, Decimal(10))
        self.assertEqual(before.remaining_msat, Decimal(990))
        self.assertEqual(len(receipts), 1)

    def test_unpaid_peer_cannot_forward(self):
        decision = self.controller.forward_frame("npub1a", "l1", 100)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.charged_msat, Decimal(0))
        self.assertEqual(self.controller.gate.journal.pending(), [])

    def test_replay_does_not_grant_second_credit(self):
        self.controller.accept_payment("npub1a", "l1",
                                       [self.proof("same")], "m")
        replay = self.proof("same")
        with self.assertRaises(ReservationInFlight):
            self.controller.accept_payment("npub1a", "l2", [replay], "m2")
        self.assertEqual(self.controller.account("npub1a").remaining_msat,
                         Decimal(1000))
        decision = self.controller.forward_frame("npub1a", "l2", 10)
        self.assertEqual(decision.charged_msat, Decimal(1))
        self.assertEqual(self.controller.account("npub1a").remaining_msat,
                         Decimal(999))

    def test_exhaustion_pauses_without_reset(self):
        self.controller.accept_payment("npub1a", "l1", [self.proof("p")], "m")
        decision = self.controller.forward_frame("npub1a", "l1", 10000)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, AccountState.GRACE)
        self.assertEqual(decision.remaining_msat, Decimal(0))
        afterward = self.controller.forward_frame("npub1a", "l1", 100)
        self.assertFalse(afterward.allowed)
        self.assertEqual(afterward.charged_msat, Decimal(0))

    def test_topup_resumes_without_resetting_used(self):
        self.controller.accept_payment("npub1a", "l1", [self.proof("old")], "m")
        self.controller.forward_frame("npub1a", "l1", 7500)
        self.assertEqual(self.controller.account("npub1a").remaining_msat,
                         Decimal(250))
        self.controller.accept_payment("npub1a", "l2", [self.proof("new")], "m2")
        account = self.controller.account("npub1a")
        self.assertEqual(account.used_msat, Decimal(750))
        self.assertEqual(account.remaining_msat, Decimal(1250))
        self.assertTrue(self.controller.forward_frame("npub1a", "l2", 100).allowed)

    def test_dormant_credit_survives_new_link(self):
        self.controller.accept_payment("npub1a", "old", [self.proof("p")], "m")
        self.controller.mark_link_down("npub1a")
        decision = self.controller.forward_frame("npub1a", "new", 100)
        self.assertEqual(decision.state, AccountState.PAID)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.remaining_msat, Decimal(990))

    def test_mismatching_payer_is_rejected(self):
        with self.assertRaisesRegex(RelayError, "proof and authenticated payer"):
            self.controller.accept_payment("npub1a", "l1",
                                           [self.proof("p", payer="npub1b")], "m")
        self.assertEqual(self.controller.forward_frame("npub1a", "l1", 100).charged_msat,
                         Decimal(0))

    def test_pending_uses_only_latest_unsettled_proofs(self):
        self.controller.accept_payment("npub1a", "l1", [self.proof("p")], "m")
        pending = self.controller.gate.journal.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].key[3], "p")

    def test_store_reopen_preserves_dormant_balance_and_usage(self):
        self.controller.accept_payment("npub1a", "l1", [self.proof("p")], "m")
        self.controller.forward_frame("npub1a", "l1", 333)
        self.controller.mark_link_down("npub1a")
        self.controller.accounts.close()
        reopened = PrepaidAccountStore(str(self.root / "accounts.sqlite3"))
        account = reopened.get_or_create("npub1a", Decimal(10))
        self.assertEqual(account.state, AccountState.DORMANT)
        self.assertEqual(account.used_msat, Decimal("33.3"))
        self.assertEqual(account.remaining_msat, Decimal("966.7"))
        self.addCleanup(reopened.close)

    def test_invalid_link_and_zero_bytes_rejected(self):
        with self.assertRaises(RelayError):
            self.controller.forward_frame("npub1a", "", 100)
        with self.assertRaises(RelayError):
            self.controller.forward_frame("npub1a", "l1", 0)


class CrcAdapterTests(unittest.TestCase):
    def test_journal_adapter_and_stale_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "journal.fjnl")
            journal = CrcNullifierJournal(path)
            reservation = journal.reserve(mint_url="http://mint", unit="sat",
                                          keyset_id="k1", nullifier="p",
                                          amount_msat=Decimal(100), now=100)
            self.assertEqual(reservation.key,
                             ("http://mint", "sat", "k1", "p"))
            self.assertEqual(journal.pending()[0].reserved_at, 100)
            settled = CrcNullifierJournal(path, recover_stale_reservations=True)
            self.assertEqual(settled.pending(), [])
            with self.assertRaises(AlreadySpent):
                settled.reserve(mint_url="http://mint", unit="sat",
                                keyset_id="k1", nullifier="p", amount_msat=100)


if __name__ == "__main__":
    unittest.main()
