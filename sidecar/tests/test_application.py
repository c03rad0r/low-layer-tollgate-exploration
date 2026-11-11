import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tollgate_fips.account import AccountState, PrepaidAccountStore
from tollgate_fips.appendlog import CrcNullifierJournal
from tollgate_fips.application import RelayApplicationHandler
from tollgate_fips.envelope import EnvelopeError, decode, encode
from tollgate_fips.exposure import ExposureLedger
from tollgate_fips.identity import FipsIdentityResolver, IdentityError
from tollgate_fips.nut11 import check_offline_condition
from tollgate_fips.relay import AppRelayController

SELLER = "02" + "ab" * 32
A_IP = "fded:0001::1"
B_IP = "fded:0002::1"


def lock():
    return ["P2PK", {"data": SELLER, "nonce": "00" * 16,
                      "tags": [["sigflag", "SIG_INPUTS"]]}]


def wire_proof(name, amount=1000):
    return {"mint": "http://mint", "unit": "sat", "keyset": "k1",
            "secret": name, "amount_msat": str(amount), "condition": lock()}


class Verifier:
    def verify(self, proof, seller_npub, msg1):
        check_offline_condition(proof.token, SELLER, proof.final_expiry)
        return True


class FakeFipsctl:
    def __init__(self):
        self.link_id = "link-1"

    def peers(self):
        return [
            {"ipv6_addr": A_IP, "npub": "npubA", "link_id": self.link_id,
             "node_addr": "node-a", "connectivity": "connected"},
            {"ipv6_addr": B_IP, "npub": "npubB", "link_id": "link-b",
             "node_addr": "node-b", "connectivity": "connected"},
        ]


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        path = Path(self.tempdir.name)
        self.controller = AppRelayController(
            CrcNullifierJournal(str(path / "proofs.fjnl")),
            ExposureLedger(str(path / "exposure.sqlite3")),
            PrepaidAccountStore(str(path / "accounts.sqlite3")),
            Verifier(), "npub1seller", cap_msat=100000,
            rate_bytes_per_msat=Decimal(10))
        self.fipsctl = FakeFipsctl()
        self.application = RelayApplicationHandler(
            self.controller, FipsIdentityResolver(self.fipsctl))

    def pay(self, name, req="req-1", amount=1000):
        return encode({"v": 1, "t": "pay", "req": req,
                       "msg1_ephemeral": "eph",
                       "proofs": [wire_proof(name, amount)]})

    def frame(self, size, req="frame-1"):
        return encode({"v": 1, "t": "frame", "req": req,
                       "frame_bytes": size})

    def test_unknown_source_is_rejected(self):
        result = self.application.handle("fded:dead::1", self.pay("p"))
        self.assertEqual(result["t"], "nack")
        self.assertEqual(result["code"], "unknown_fips_peer")

    def test_source_binding_credits_authenticated_npub(self):
        result = self.application.handle(A_IP, self.pay("p1"))
        self.assertEqual(result["t"], "ack")
        self.assertEqual(result["req"], "req-1")
        self.assertEqual(result["state"], "paid")
        self.assertEqual(result["remaining_msat"], "1000")

    def test_second_peer_replay_is_rejected(self):
        self.application.handle(A_IP, self.pay("p1"))
        result = self.application.handle(B_IP, self.pay("p1", "req-2"))
        self.assertEqual(result["t"], "nack")
        self.assertEqual(result["code"], "reservation_in_flight")

    def test_frame_accounting_and_exhaustion(self):
        self.application.handle(A_IP, self.pay("p1"))
        result = self.application.handle(A_IP, self.frame(10000))
        self.assertTrue(result["allowed"])
        self.assertEqual(result["state"], "grace")
        result2 = self.application.handle(A_IP, self.frame(10))
        self.assertFalse(result2["allowed"])
        self.assertEqual(result2["charged_msat"], "0")

    def test_rebind_resumes_npup_credit(self):
        self.application.handle(A_IP, self.pay("p1"))
        link_down = encode({"v": 1, "t": "link_down"})
        self.application.handle(A_IP, link_down)
        self.fipsctl.link_id = "link-2"
        result = self.application.handle(A_IP, self.frame(100))
        self.assertTrue(result["allowed"])
        self.assertEqual(self.controller.account("npubA").link_id, "link-2")

    def test_bad_envelope_cannot_grant_credit(self):
        result = self.application.handle(A_IP, b"not json")
        self.assertEqual(result["code"], "invalid_envelope")
        self.assertEqual(self.controller.account("npubA").remaining_msat, Decimal(0))

    def test_invalid_frame_size_cannot_charge(self):
        self.application.handle(A_IP, self.pay("p1"))
        result = self.application.handle(A_IP, encode(
            {"v": 1, "t": "frame", "frame_bytes": 0}))
        self.assertEqual(result["t"], "nack")
        self.assertEqual(self.controller.account("npubA").remaining_msat,
                         Decimal(1000))

    def test_invalid_lock_fails_closed(self):
        proof = dict(wire_proof("p1"))
        proof["condition"] = ["P2PK", {"data": "03" + "cd" * 32}]
        req = encode({"v": 1, "t": "pay", "msg1_ephemeral": "eph",
                      "proofs": [proof]})
        result = self.application.handle(A_IP, req)
        self.assertEqual(result["code"], "invalid_offline_condition")
        self.assertEqual(self.controller.account("npubA").remaining_msat,
                         Decimal(0))

    def test_wire_fields_set_flags(self):
        with self.assertRaises(EnvelopeError):
            decode(encode({"v": 2, "t": "pay"}))
        with self.assertRaises(EnvelopeError):
            decode(b"[1,2,3]")


if __name__ == "__main__":
    unittest.main()
