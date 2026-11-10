import unittest

from tollgate_fips.nut11 import (
    OfflineProofRejected,
    check_offline_condition,
    is_compressed_secp256k1,
    require_compressed_lock_key,
)

SELLER = "02" + "ab" * 32
OTHER = "03" + "cd" * 32
FAR_EXPIRY = 1000000000


def condition(seller=SELLER, fields=None, tags=None):
    payload = {"data": seller, "nonce": "00" * 16,
               "tags": tags if tags is not None else [["sigflag", "SIG_INPUTS"]]}
    if fields:
        payload.update(fields)
    return ["P2PK", payload]


class Nut11Tests(unittest.TestCase):
    def test_exact_one_of_one_lock_is_accepted(self):
        check_offline_condition(condition(), SELLER,
                                final_expiry=FAR_EXPIRY,
                                settlement_window=3600, now=100)
        check_offline_condition(__import__("json").dumps(condition()), SELLER,
                                final_expiry=None, now=100)

    def test_signature_must_use_expected_key(self):
        with self.assertRaisesRegex(OfflineProofRejected, "not this balloon"):
            check_offline_condition(condition(), OTHER, now=100)

    def test_refund_is_rejected_even_with_far_locktime(self):
        case = condition(tags=[["sigflag", "SIG_INPUTS"],
                               ["refund", OTHER],
                               ["locktime", far_future := str(FAR_EXPIRY + 1000)]])
        with self.assertRaisesRegex(OfflineProofRejected, "reclaim path"):
            check_offline_condition(case, SELLER, now=100)

    def test_locktime_is_rejected_for_offline_credit(self):
        for value in ("1790000000", "1790000001"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(OfflineProofRejected, "locktime"):
                    check_offline_condition(
                        condition(tags=[["locktime", value]]), SELLER, now=100)

    def test_multisig_and_adjustable_signatures_rejected(self):
        for key, value in (("n_sigs", "2"), ("pubkeys", OTHER)):
            with self.subTest(key=key):
                with self.assertRaisesRegex(OfflineProofRejected, "not allowed"):
                    check_offline_condition(condition(tags=[[key, value]]),
                                            SELLER, now=100)

    def test_grouped_signing_rejected(self):
        with self.assertRaisesRegex(OfflineProofRejected, "grouped"):
            check_offline_condition(condition(tags=[["sigflag", "SIG_ALL"]]),
                                    SELLER, now=100)

    def test_unknown_tag_fails_closed(self):
        with self.assertRaisesRegex(OfflineProofRejected, "unknown P2PK extension"):
            check_offline_condition(condition(tags=[["future_reclaim_flag", "1"]]),
                                    SELLER, now=100)

    def test_unknown_condition_field_fails_closed(self):
        with self.assertRaisesRegex(OfflineProofRejected, "unknown P2PK condition fields"):
            check_offline_condition(condition(fields={"refund_time": "0"}),
                                    SELLER, now=100)

    def test_malformed_condition_shapes_rejected(self):
        for case in ("not-json", [], ["HTLC", {}], ["P2PK", "not-a-dict"],
                     ["P2PK", {"data": SELLER, "tags": "SIG_INPUTS"}]):
            with self.subTest(case=case):
                with self.assertRaises(OfflineProofRejected):
                    check_offline_condition(case, SELLER, now=100)

    def test_keyset_expiry_uses_settlement_window(self):
        with self.assertRaisesRegex(OfflineProofRejected, "settlement window"):
            check_offline_condition(condition(), SELLER, final_expiry=150,
                                    settlement_window=100, now=100)
        check_offline_condition(condition(), SELLER, final_expiry=200,
                                settlement_window=100, now=100)

    def test_compressed_key_is_exactly_33_bytes(self):
        self.assertTrue(is_compressed_secp256k1(SELLER))
        self.assertTrue(is_compressed_secp256k1(OTHER))
        self.assertFalse(is_compressed_secp256k1("ab" * 32))
        self.assertFalse(is_compressed_secp256k1("01" + "ab" * 32))
        self.assertFalse(is_compressed_secp256k1(SELLER[:-2]))
        self.assertFalse(is_compressed_secp256k1(" " + SELLER))

    def test_offer_rejects_x_only_npub(self):
        self.assertEqual(require_compressed_lock_key(SELLER), SELLER)
        with self.assertRaisesRegex(OfflineProofRejected, "not an npub"):
            require_compressed_lock_key("ab" * 32)

    def test_invalid_tag_shapes_rejected(self):
        for tags in ({}, [["sigflag"], [b"sigflag", "SIG_INPUTS"]]):
            with self.subTest(tags=tags):
                with self.assertRaises(OfflineProofRejected):
                    check_offline_condition(condition(tags=tags), SELLER, now=100)


if __name__ == "__main__":
    unittest.main()
