import os
import tempfile
import unittest
from decimal import Decimal

from tollgate_fips.drain import SettlementDaemon
from tollgate_fips.exposure import ExposureKey, ExposureLedger
from tollgate_fips.journal import NullifierJournal
from tollgate_fips.settlement import SettlementWorker
from tollgate_fips.vault import TokenVault

MINT = "https://mint.test"
UNIT = "sat"
KEYSET = "009a1f293253e41e"
NULLIFIER = "a" * 64
PAYER = "npub1payer"


class FakeRedeemer:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def redeem_many(self, tokens):
        self.calls += 1
        if not self.ok:
            return {"ok": False, "error": "refused"}
        return {"ok": True, "tokens": len(tokens), "fee_sat": 1,
                "input_fee_ppk": 100}


class DrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = NullifierJournal(os.path.join(self.tmp.name, "j.sqlite3"))
        self.exposure = ExposureLedger(os.path.join(self.tmp.name, "e.sqlite3"))
        self.vault = TokenVault(os.path.join(self.tmp.name, "v.sqlite3"))
        self.key = ExposureKey(PAYER, MINT, UNIT)
        self.reservation = self.journal.reserve(
            mint_url=MINT, unit=UNIT, keyset_id=KEYSET,
            nullifier=NULLIFIER, amount_msat=Decimal("2"))
        self.exposure.reserve(self.key, Decimal("2"), 1000)

    def tearDown(self):
        self.journal.close()
        self.exposure.close()
        self.vault.close()
        self.tmp.cleanup()

    def add_token(self, token="cashuBtoken"):
        self.vault.put(token=token, payer_npub=PAYER, mint_url=MINT, unit=UNIT,
                       keyset_id=KEYSET, nullifier=NULLIFIER,
                       amount_msat=Decimal("2"))

    def test_run_once_drains_and_resets_backoff(self):
        self.add_token()
        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure, FakeRedeemer()),
            poll_seconds=5, sleep=lambda _: None)
        result = daemon.run_once()
        self.assertEqual(result.settled, 1)
        self.assertEqual(daemon.backoff, 5)
        self.assertEqual(self.vault.pending(), [])

    def test_failure_backs_off_up_to_the_cap(self):
        self.add_token()
        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure,
                             FakeRedeemer(ok=False)),
            poll_seconds=5, max_backoff_seconds=20, sleep=lambda _: None)
        for expected in (10, 20, 20):
            daemon.run_once()
            self.assertEqual(daemon.backoff, expected)

    def test_run_stops_after_max_passes(self):
        self.add_token()
        sleeps = []
        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure, FakeRedeemer()),
            poll_seconds=5, sleep=sleeps.append)
        stats = daemon.run(max_passes=3)
        self.assertEqual(stats.passes, 3)
        self.assertEqual(stats.settled, 1)   # only the first pass had a token
        self.assertEqual(len(sleeps), 2)

    def test_stop_predicate_ends_the_loop(self):
        self.add_token()
        passes = {"n": 0}

        def stop():
            passes["n"] += 1
            return passes["n"] > 2

        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure, FakeRedeemer()),
            poll_seconds=1, sleep=lambda _: None)
        stats = daemon.run(stop=stop)
        self.assertGreaterEqual(stats.passes, 1)

    def test_dead_letter_after_max_attempts_then_requeue(self):
        self.add_token()
        redeemer = FakeRedeemer(ok=False)
        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure, redeemer),
            poll_seconds=1, max_attempts=3, sleep=lambda _: None)

        for _ in range(3):
            daemon.run_once()
        self.assertEqual(redeemer.calls, 3)
        self.assertEqual(self.vault.pending(), [])
        self.assertEqual(len(self.vault.dead_lettered()), 1)

        health = daemon.health()
        self.assertEqual(health.dead_lettered, 1)
        self.assertEqual(health.pending, 0)
        self.assertEqual(health.consecutive_failures, 3)
        self.assertIsNotNone(health.last_error)

        # Dead letters are not retried.
        daemon.run_once()
        self.assertEqual(redeemer.calls, 3)

        # After the cause is fixed, requeue and settle.
        key = daemon.dead_letters()[0].vault_key
        self.assertTrue(daemon.requeue(key))
        daemon.worker.redeemer = FakeRedeemer()
        result = daemon.run_once()
        self.assertEqual(result.settled, 1)
        self.assertEqual(daemon.health().dead_lettered, 0)
        self.assertEqual(daemon.health().pending, 0)

    def test_health_records_last_pass_and_success(self):
        self.add_token()
        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure, FakeRedeemer()),
            poll_seconds=5, wall_clock=lambda: 1000.0,
            sleep=lambda _: None)
        health = daemon.health()
        self.assertIsNone(health.last_pass_at)
        self.assertEqual(health.pending, 1)

        daemon.run_once()
        health = daemon.health()
        self.assertEqual(health.last_pass_at, 1000.0)
        self.assertEqual(health.last_success_at, 1000.0)
        self.assertEqual(health.consecutive_failures, 0)
        self.assertIsNone(health.last_error)
        self.assertEqual(health.pending, 0)
        self.assertEqual(health.settled, 1)

    def test_empty_vault_resets_the_backoff(self):
        daemon = SettlementDaemon(
            self.vault,
            SettlementWorker(self.journal, self.exposure, FakeRedeemer()),
            poll_seconds=5, max_backoff_seconds=20, sleep=lambda _: None)
        daemon.backoff = 20
        daemon.run_once()
        self.assertEqual(daemon.backoff, 5)

    def test_invalid_intervals_are_refused(self):
        worker = SettlementWorker(self.journal, self.exposure, FakeRedeemer())
        with self.assertRaises(ValueError):
            SettlementDaemon(self.vault, worker, poll_seconds=0)
        with self.assertRaises(ValueError):
            SettlementDaemon(self.vault, worker, poll_seconds=10,
                             max_backoff_seconds=5)
        with self.assertRaises(ValueError):
            SettlementDaemon(self.vault, worker, poll_seconds=10,
                             max_attempts=0)


if __name__ == "__main__":
    unittest.main()
