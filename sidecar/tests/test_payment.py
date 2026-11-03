import os
import tempfile
import unittest
from decimal import Decimal

from tollgate_fips.exposure import (
    ExposureExceeded,
    ExposureKey,
    ExposureLedger,
)
from tollgate_fips.journal import NullifierJournal, ReservationInFlight
from tollgate_fips.vault import TokenVault, vault_key
from tollgate_fips.payment import (
    PaymentError,
    PaymentGate,
    PaymentProof,
    ProofRejected,
    VerificationFailed,
)

MINT = "https://mint.test"
UNIT = "sat"
KEYSET = "009a1f293253e41e"
NULLIFIER = "b" * 64
SELLER = "npub1seller"
PAYER = "npub1payer"


class FakeVerifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def verify(self, proof, seller_npub, msg1_ephemeral):
        self.calls.append((proof, seller_npub, msg1_ephemeral))
        return self.ok


class PaymentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = NullifierJournal(os.path.join(self.tmp.name, "j.sqlite3"))
        self.exposure = ExposureLedger(os.path.join(self.tmp.name, "e.sqlite3"))
        self.verifier = FakeVerifier()
        self.gate = PaymentGate(
            self.journal, self.exposure, self.verifier, SELLER,
            cap_msat=100, settlement_window_secs=1000,
        )

    def tearDown(self):
        self.journal.close()
        self.exposure.close()
        self.tmp.cleanup()

    def proof(self, **kwargs):
        defaults = dict(
            mint_url=MINT, unit=UNIT, keyset_id=KEYSET, nullifier=NULLIFIER,
            amount_msat=Decimal("40"), payer_npub=PAYER,
            final_expiry=2_000_000_000, token={"secret": "x"},
        )
        defaults.update(kwargs)
        return PaymentProof(**defaults)

    def test_accept_records_both_ledgers(self):
        receipt = self.gate.accept(self.proof(), "msg1-ephemeral")
        self.assertEqual(receipt.proof.nullifier, NULLIFIER)
        self.assertEqual(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER),
                         "RESERVED")
        key = receipt.exposure_key
        self.assertEqual(self.exposure.outstanding(key), Decimal("40"))
        self.assertEqual(len(self.verifier.calls), 1)
        self.assertEqual(self.verifier.calls[0][1], SELLER)
        self.assertEqual(self.verifier.calls[0][2], "msg1-ephemeral")

    def test_verification_failure_takes_nothing(self):
        self.verifier.ok = False
        with self.assertRaises(VerificationFailed):
            self.gate.accept(self.proof(), "eph")
        self.assertIsNone(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER))
        self.assertEqual(
            self.exposure.outstanding(ExposureKey(PAYER, MINT, UNIT)),
            Decimal(0),
        )

    def test_cap_refuses_before_the_journal(self):
        self.gate.accept(self.proof(amount_msat=Decimal("90")), "eph")
        with self.assertRaises(ExposureExceeded):
            self.gate.accept(self.proof(
                nullifier="c" * 64, amount_msat=Decimal("20")), "eph")
        self.assertIsNone(self.journal.state(MINT, UNIT, KEYSET, "c" * 64))

    def test_replay_releases_the_second_exposure(self):
        self.gate.accept(self.proof(), "eph")
        with self.assertRaises(ReservationInFlight):
            self.gate.accept(self.proof(), "eph")
        self.assertEqual(
            self.exposure.outstanding(ExposureKey(PAYER, MINT, UNIT)),
            Decimal("40"),
        )

    def test_vault_persists_the_token_before_the_journal_row(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            self.gate.accept(self.proof(), "eph", vault=vault, token="cashuBx")
            key = vault_key(MINT, UNIT, KEYSET, NULLIFIER)
            self.assertEqual(vault.get(key).token, "cashuBx")
            self.assertEqual(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER),
                             "RESERVED")
        finally:
            vault.close()

    def test_vault_replay_does_not_replace_or_delete_the_first_row(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            self.gate.accept(self.proof(), "eph", vault=vault, token="cashuBfirst")
            with self.assertRaises(ReservationInFlight):
                self.gate.accept(self.proof(), "eph", vault=vault,
                                 token="cashuBsecond")
            key = vault_key(MINT, UNIT, KEYSET, NULLIFIER)
            self.assertEqual(vault.get(key).token, "cashuBfirst")
        finally:
            vault.close()

    def test_vault_requires_a_token(self):
        vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        try:
            with self.assertRaises(PaymentError):
                self.gate.accept(self.proof(), "eph", vault=vault, token=None)
            self.assertIsNone(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER))
        finally:
            vault.close()

    def test_settle_closes_journal_and_exposure(self):
        receipt = self.gate.accept(self.proof(), "eph")
        self.gate.settle(receipt)
        self.assertEqual(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER),
                         "SETTLED")
        self.assertEqual(self.exposure.outstanding(receipt.exposure_key),
                         Decimal("0"))

    def test_reject_marks_spent_and_releases(self):
        receipt = self.gate.accept(self.proof(), "eph")
        self.gate.reject(receipt, note="double spend")
        self.assertEqual(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER),
                         "SPENT")
        self.assertEqual(self.exposure.outstanding(receipt.exposure_key),
                         Decimal("0"))

    def test_expired_keyset_is_rejected_before_verify(self):
        with self.assertRaises(ProofRejected):
            self.gate.accept(self.proof(final_expiry=1_500), "eph",
                             now=1_000)
        self.assertEqual(self.verifier.calls, [])
        self.assertIsNone(self.journal.state(MINT, UNIT, KEYSET, NULLIFIER))

    def test_invalid_amount_and_payer(self):
        with self.assertRaises(PaymentError):
            self.gate.accept(self.proof(amount_msat=Decimal("0")), "eph")
        with self.assertRaises(PaymentError):
            self.gate.accept(self.proof(payer_npub=""), "eph")


if __name__ == "__main__":
    unittest.main()
