import unittest
from decimal import Decimal

from tollgate_fips.session import Session, SessionError, State


def make(**kwargs):
    defaults = dict(
        npub="npub1test",
        rate_bytes_per_msat=Decimal("100"),
        allotment_msat=Decimal(0),
        grace_seconds=30.0,
        admission_seconds=30.0,
        issued_at_mono=0.0,
    )
    defaults.update(kwargs)
    return Session(**defaults)


class SessionTest(unittest.TestCase):
    def test_initial_state_is_unpaid(self):
        s = make()
        self.assertIs(s.state, State.UNPAID)
        self.assertFalse(s.forwarding_allowed)
        self.assertTrue(s.payment_lane_open)

    def test_payment_opens_forwarding(self):
        s = make()
        s.pay(Decimal("1000"), now=0)
        self.assertIs(s.state, State.PAID)
        self.assertTrue(s.forwarding_allowed)

    def test_charge_until_exhaustion_enters_grace(self):
        s = make()
        s.pay(Decimal("1000"), now=0)
        cost = s.charge(100_000, now=0)   # 100000 / 100 = 1000 msat
        self.assertEqual(cost, Decimal("1000"))
        self.assertIs(s.state, State.GRACE)
        self.assertFalse(s.forwarding_allowed)
        self.assertTrue(s.payment_lane_open)
        self.assertTrue(s.link_open)
        self.assertEqual(s.grace_deadline_mono, 30.0)

    def test_no_charge_when_not_paid(self):
        s = make()
        self.assertEqual(s.charge(100_000, now=0), Decimal(0))
        self.assertIs(s.state, State.UNPAID)

    def test_renewal_returns_to_paid_without_new_link(self):
        s = make()
        s.pay(Decimal("1000"), now=0)
        s.charge(100_000, now=0)
        self.assertIs(s.state, State.GRACE)
        s.pay(Decimal("500"), now=1)
        self.assertIs(s.state, State.PAID)
        self.assertEqual(s.remaining_msat, Decimal("500"))

    def test_grace_expiry_evicts(self):
        s = make()
        s.pay(Decimal("1000"), now=0)
        s.charge(100_000, now=0)
        s.tick(now=29)
        self.assertIs(s.state, State.GRACE)
        s.tick(now=31)
        self.assertIs(s.state, State.EVICTED)
        self.assertEqual(s.evicted_reason, "grace expired")
        self.assertFalse(s.payment_lane_open)

    def test_admission_timeout_evicts_unpaid(self):
        s = make()
        s.tick(now=31)
        self.assertIs(s.state, State.EVICTED)
        self.assertEqual(s.evicted_reason, "admission timeout")

    def test_absolute_deadline_moves_paid_to_grace_not_evicted(self):
        s = make(max_session_seconds=10)
        s.pay(Decimal("1000"), now=0)
        s.tick(now=11)
        self.assertIs(s.state, State.GRACE)
        self.assertTrue(s.link_open)
        s.tick(now=42)
        self.assertIs(s.state, State.EVICTED)

    def test_deadline_is_min_of_local_and_valid_until(self):
        s = make(max_session_seconds=100, valid_until_mono=20)
        self.assertEqual(s.deadline_mono, 20)

    def test_notice_codes_and_rate_limit(self):
        s = make()
        n = s.notice(now=0)
        self.assertEqual(n.code, "payment-required")
        self.assertEqual(n.level, "info")
        self.assertIsNone(s.notice(now=5))   # rate-limited
        self.assertIsNone(s.notice(now=9))   # still rate-limited

        s.pay(Decimal("1000"), now=10)
        s.charge(85_000, now=10)  # 850 of 1000, over 80 %
        due = s.notice(now=10)    # 10 s since the last notice
        self.assertIsNotNone(due)
        self.assertEqual(due.code, "payment-due")

        s.charge(20_000, now=10)  # now in grace
        self.assertIsNone(s.notice(now=11))  # rate-limited
        exhausted = s.notice(now=21)
        self.assertIsNotNone(exhausted)
        self.assertEqual(exhausted.code, "session-exhausted")
        self.assertEqual(exhausted.level, "error")
        self.assertIsNotNone(exhausted.retry_after)

    def test_pay_evicted_session_raises(self):
        s = make()
        s.tick(now=31)
        with self.assertRaises(SessionError):
            s.pay(Decimal("1"), now=32)

    def test_negative_charge_rejected(self):
        s = make()
        with self.assertRaises(SessionError):
            s.charge(-1, now=0)


if __name__ == "__main__":
    unittest.main()
