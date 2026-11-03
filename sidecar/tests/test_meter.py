import unittest
from decimal import Decimal

from tollgate_fips.meter import MeterError, counter_delta, delta, snapshot


PEERS = [
    {
        "npub": "npub1aaa",
        "link_id": 1,
        "transport_type": "udp",
        "transport_addr": "10.0.0.1:2121",
        "stats": {"bytes_sent": 2000, "bytes_recv": 1000,
                  "packets_sent": 20, "packets_recv": 10},
    },
    {
        "npub": "npub1aaa",
        "link_id": 2,
        "transport_type": "tcp",
        "transport_addr": "10.0.0.2:2121",
        "stats": {"bytes_sent": 100, "bytes_recv": 500,
                  "packets_sent": 1, "packets_recv": 5},
    },
    {
        "npub": "npub1bbb",
        "link_id": 3,
        "transport_type": "udp",
        "transport_addr": "10.0.0.3:2121",
        "stats": {"bytes_sent": 100, "bytes_recv": 100,
                  "packets_sent": 1, "packets_recv": 1},
    },
]

LINKS = [
    {"link_id": 1, "transport_id": 7, "remote_addr": "10.0.0.1:2121"},
    {"link_id": 2, "transport_id": 8, "remote_addr": "10.0.0.2:2121"},
]


class MeterTest(unittest.TestCase):
    def test_snapshot_merges_link_metadata(self):
        snap = snapshot(PEERS, LINKS)
        self.assertEqual(len(snap), 3)
        first = snap[("npub1aaa", 1)]
        self.assertEqual(first.transport_id, 7)
        self.assertEqual(first.remote_addr, "10.0.0.1:2121")
        self.assertEqual(first.transport_type, "udp")

    def test_missing_link_metadata_is_tolerated(self):
        snap = snapshot(PEERS, [])
        self.assertIsNone(snap[("npub1aaa", 1)].transport_id)

    def test_delta_sums_links_by_npub(self):
        prev = snapshot(PEERS, LINKS)
        cur = snapshot([
            {**PEERS[0], "stats": {"bytes_sent": 2100, "bytes_recv": 1100,
                                   "packets_sent": 21, "packets_recv": 11}},
            {**PEERS[1], "stats": {"bytes_sent": 120, "bytes_recv": 550,
                                   "packets_sent": 2, "packets_recv": 6}},
            {**PEERS[2], "stats": {"bytes_sent": 100, "bytes_recv": 100,
                                   "packets_sent": 1, "packets_recv": 1}},
        ], LINKS)
        readings = {r.npub: r for r in delta(prev, cur, Decimal("1000"), "both")}
        a = readings["npub1aaa"]
        self.assertEqual(a.bytes_in, 150)
        self.assertEqual(a.bytes_out, 120)
        self.assertEqual(a.billable_bytes, 270)
        self.assertEqual(a.cost_msat, Decimal("0.27"))
        self.assertEqual(readings["npub1bbb"].billable_bytes, 0)

    def test_direction_filter(self):
        prev = snapshot([], [])
        cur = snapshot(PEERS, LINKS)
        by_in = {r.npub: r for r in delta(prev, cur, Decimal("100"), "in")}
        by_out = {r.npub: r for r in delta(prev, cur, Decimal("100"), "out")}
        self.assertEqual(by_in["npub1aaa"].billable_bytes, 1500)
        self.assertEqual(by_out["npub1aaa"].billable_bytes, 2100)
        self.assertEqual(by_in["npub1aaa"].bytes_in, 1500)
        self.assertEqual(by_out["npub1aaa"].bytes_out, 2100)

    def test_counter_reset_uses_current_value(self):
        self.assertEqual(counter_delta(1000, 50), 50)
        self.assertEqual(counter_delta(1000, 1000), 0)
        self.assertEqual(counter_delta(1000, 1200), 200)

    def test_reset_is_per_link(self):
        prev = snapshot([{**PEERS[0], "stats": {
            "bytes_sent": 1000, "bytes_recv": 1000,
            "packets_sent": 1, "packets_recv": 1}}], [])
        cur = snapshot([{**PEERS[0], "stats": {
            "bytes_sent": 50, "bytes_recv": 50,
            "packets_sent": 1, "packets_recv": 1}}], [])
        reading = delta(prev, cur, Decimal("1"), "both")[0]
        self.assertEqual(reading.billable_bytes, 100)

    def test_policy_dropped_bytes_are_not_billable(self):
        previous = snapshot(PEERS)
        current = snapshot([dict(peer, stats=dict(peer["stats"]))
                            for peer in PEERS])
        for peer in current.values():
            if peer.npub == "npub1aaa":
                object.__setattr__(peer, "bytes_recv", peer.bytes_recv + 200)
                object.__setattr__(peer, "bytes_sent", peer.bytes_sent + 100)
        reading = next(r for r in delta(
            previous, current, policy_previous={"npub1aaa": 10},
            policy_current={"npub1aaa": 250},
        ) if r.npub == "npub1aaa")
        # npub1aaa has two links; both moved by +200 recv / +100 sent.
        self.assertEqual(reading.wire_bytes, 600)
        self.assertEqual(reading.policy_dropped_bytes, 240)
        self.assertEqual(reading.billable_bytes, 360)

    def test_policy_subtraction_is_inbound_only(self):
        previous = snapshot(PEERS)
        current = snapshot(PEERS)
        out = next(r for r in delta(
            previous, current, direction="out",
            policy_previous={"npub1aaa": 0}, policy_current={"npub1aaa": 999},
        ) if r.npub == "npub1aaa")
        # Identical snapshots, so the window delta is zero on both sides;
        # the point is that an outbound reading never subtracts a policy drop.
        self.assertEqual(out.wire_bytes, 0)
        self.assertEqual(out.billable_bytes, 0)
        self.assertEqual(out.policy_dropped_bytes, 999)

    def test_policy_subtraction_clamps_at_zero(self):
        previous = snapshot(PEERS)
        current = snapshot(PEERS)
        reading = next(r for r in delta(
            previous, current, policy_previous={"npub1aaa": 0},
            policy_current={"npub1aaa": 999},
        ) if r.npub == "npub1aaa")
        self.assertEqual(reading.wire_bytes, 0)
        self.assertEqual(reading.billable_bytes, 0)

    def test_policy_counter_reset_uses_current_value(self):
        previous = snapshot(PEERS)
        current = snapshot(PEERS)
        reading = next(r for r in delta(
            previous, current, policy_previous={"npub1aaa": 500},
            policy_current={"npub1aaa": 40},
        ) if r.npub == "npub1aaa")
        self.assertEqual(reading.policy_dropped_bytes, 40)

    def test_policy_omitted_keeps_all_frames(self):
        previous = snapshot(PEERS)
        current = snapshot(PEERS)
        reading = next(r for r in delta(previous, current)
                       if r.npub == "npub1aaa")
        self.assertEqual(reading.policy_dropped_bytes, 0)
        self.assertEqual(reading.billable_bytes, reading.wire_bytes)

    def test_invalid_direction_and_rate(self):
        with self.assertRaises(MeterError):
            delta({}, {}, Decimal("1"), "sideways")
        with self.assertRaises(MeterError):
            delta({}, {}, Decimal("0"), "both")


if __name__ == "__main__":
    unittest.main()
