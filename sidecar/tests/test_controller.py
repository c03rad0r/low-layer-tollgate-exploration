import unittest
from decimal import Decimal

from tollgate_fips.controller import (
    ControllerConfig,
    ControllerError,
    SellerController,
)
from tollgate_fips.session import Session


class FakePeers:
    def __init__(self):
        self.rows = []
        self.policy = 0

    def peers(self):
        return self.rows

    def links(self):
        return []


class FakeGate:
    """Minimal gate surface used by the controller."""

    def __init__(self):
        self.fipsctl = FakePeers()
        self.pauses = []
        self.resumes = []
        self.evicts = []
        self.pause_mode = "transit-blocked"

    def pause(self, npub):
        self.pauses.append(npub)

        class Result:
            mode = self.pause_mode
        return Result()

    def resume(self, npub):
        self.resumes.append(npub)
        return {"forwarding": "allowed"}

    def evict(self, npub):
        self.evicts.append(npub)

        class Result:
            mode = "runtime+deny+disconnect"
        return Result()

    def policy_blocked_for(self, npub):
        return {"peer": "p", "packets": 0, "bytes": self.fipsctl.policy}

    def set_counters(self, recv, sent, policy=0):
        self.fipsctl.rows = [{
            "npub": "npub1buyer",
            "link_id": 1,
            "stats": {"bytes_recv": recv, "bytes_sent": sent,
                      "packets_recv": 0, "packets_sent": 0},
        }]
        self.fipsctl.policy = policy


class ControllerTest(unittest.TestCase):
    def setUp(self):
        self.gate = FakeGate()
        self.session = Session(
            npub="npub1buyer", rate_bytes_per_msat=Decimal("1"),
            allotment_msat=Decimal(0), grace_seconds=30.0,
        )
        self.session.pay(Decimal(100))
        self.controller = SellerController(
            self.gate, self.session,
            ControllerConfig(rate_bytes_per_msat=Decimal("1"), tick_seconds=0),
        )
        self.gate.set_counters(0, 0)

    def test_first_tick_only_establishes_the_baseline(self):
        result = self.controller.tick()
        self.assertEqual(result.billable_bytes, 0)
        self.assertEqual(result.actions, [])

    def test_paid_tick_charges_the_delta(self):
        self.controller.tick()
        self.gate.set_counters(60, 0)
        result = self.controller.tick()
        self.assertEqual(result.billable_bytes, 60)
        self.assertEqual(self.session.used_msat, Decimal(60))

    def test_exhaustion_pauses_once(self):
        self.controller.tick()
        self.gate.set_counters(150, 0)
        result = self.controller.tick()
        self.assertEqual(self.session.state.value, "grace")
        self.assertEqual(result.actions, ["pause:transit-blocked"])
        self.assertTrue(self.controller.paused)

        self.gate.set_counters(400, 0)
        result = self.controller.tick()
        self.assertEqual(result.actions, [])
        self.assertEqual(len(self.gate.pauses), 1)

    def test_paused_bytes_are_not_billed_on_resume(self):
        self.controller.tick()
        self.gate.set_counters(150, 0)
        self.controller.tick()
        self.assertTrue(self.controller.paused)

        # Bytes accrue while paused; the baseline advances, nothing is charged.
        self.gate.set_counters(900, 500)
        self.controller.tick()
        self.assertEqual(self.session.used_msat, Decimal(150))

        self.controller.on_payment(Decimal(100))
        self.assertFalse(self.controller.paused)
        self.assertEqual(self.gate.resumes, ["npub1buyer"])

        # Only new traffic after resume is billable.
        self.gate.set_counters(1000, 500)
        result = self.controller.tick()
        self.assertEqual(result.billable_bytes, 100)
        self.assertEqual(self.session.used_msat, Decimal(250))

    def test_policy_drop_delta_is_subtracted(self):
        self.controller.tick()
        self.gate.set_counters(1000, 0, policy=600)
        result = self.controller.tick()
        self.assertEqual(result.billable_bytes, 400)

    def test_absolute_deadline_pauses(self):
        self.session.max_session_seconds = 10
        self.session.issued_at_mono = 0.0
        self.controller.tick(now=0.0)
        result = self.controller.tick(now=11.0)
        self.assertEqual(self.session.state.value, "grace")
        self.assertIn("pause:transit-blocked", result.actions)

    def test_eviction_is_durable_and_once(self):
        self.session.grace_seconds = 0.0
        self.controller.tick(now=0.0)
        self.session.charge(self.session.allotment_msat, now=1.0)
        self.assertEqual(self.session.state.value, "grace")
        result = self.controller.tick(now=2.0)
        self.assertEqual(self.session.state.value, "evicted")
        self.assertEqual(result.actions, ["evict:runtime+deny+disconnect"])
        self.controller.tick(now=3.0)
        self.assertEqual(len(self.gate.evicts), 1)

    def test_payment_after_eviction_is_refused(self):
        self.session._evict("test", 0.0)
        with self.assertRaises(ControllerError):
            self.controller.on_payment(Decimal(10))


if __name__ == "__main__":
    unittest.main()
