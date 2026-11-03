import os
import tempfile
import unittest
from decimal import Decimal

from tollgate_fips.control import ControlError
from tollgate_fips.gate import (
    AclError,
    FipsGate,
    FileAclStore,
    GateError,
    PauseUnsupported,
    PeerNotFound,
)
from tollgate_fips.meter import snapshot


class FakeControl:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def set_forwarding(self, npub, allow):
        self.calls.append((npub, allow))
        if self.fail:
            raise ControlError("unknown command: set_forwarding")
        return {"npub": npub, "forwarding": "allowed" if allow else "blocked"}

    def set_admission(self, npub, action):
        self.calls.append((npub, action))
        if self.fail:
            raise ControlError("unknown command: set_admission")
        return {"npub": npub, "admission": action}


class FakeFipsctl:
    def __init__(self, peers, links, store=None):
        self._peers = peers
        self._links = links
        self.store = store
        self.disconnected = []

    def peers(self):
        return self._peers

    def links(self):
        return self._links

    def acl(self):
        if self.store is None:
            return {"allow_entries": [], "deny_entries": [], "deny_all": False}
        allow, deny = self.store.entries()
        return {
            "allow_entries": allow,
            "deny_entries": deny,
            "deny_all": "ALL" in deny,
        }

    def policy_blocked(self):
        return {"packets": 14, "bytes": 2063}

    def policy_blocked_for(self, npub):
        return {"peer": "peer-" + npub, "packets": 2, "bytes": 120}

    def disconnect(self, peer):
        self.disconnected.append(peer)
        return f"disconnected {peer}"


PEERS = [{
    "npub": "npub1aaa",
    "link_id": 1,
    "transport_type": "udp",
    "transport_addr": "10.0.0.1:2121",
    "stats": {"bytes_sent": 2000, "bytes_recv": 1000,
              "packets_sent": 20, "packets_recv": 10},
}]
LINKS = [{"link_id": 1, "transport_id": 7, "remote_addr": "10.0.0.1:2121"}]


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.allow = os.path.join(self.tmp.name, "peers.allow")
        self.deny = os.path.join(self.tmp.name, "peers.deny")
        for path in (self.allow, self.deny):
            open(path, "w").close()
        self.store = FileAclStore(self.allow, self.deny)
        self.fips = FakeFipsctl(PEERS, LINKS, self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_admit_is_idempotent(self):
        gate = FipsGate(self.fips, self.store)
        self.assertTrue(gate.admit("npub1aaa"))
        self.assertFalse(gate.admit("npub1aaa"))
        self.assertTrue(self.store.allowed("npub1aaa"))

    def test_deny_is_idempotent(self):
        gate = FipsGate(self.fips, self.store)
        self.assertTrue(gate.deny("npub1bad"))
        self.assertFalse(gate.deny("npub1bad"))
        self.assertTrue(self.store.denied("npub1bad"))

    def test_admit_removes_a_deny_entry(self):
        gate = FipsGate(self.fips, self.store)
        gate.deny("npub1aaa")
        self.assertTrue(self.store.denied("npub1aaa"))
        gate.admit("npub1aaa")
        self.assertFalse(self.store.denied("npub1aaa"))
        self.assertTrue(self.store.allowed("npub1aaa"))

    def test_deny_removes_an_allow_entry(self):
        gate = FipsGate(self.fips, self.store)
        gate.admit("npub1aaa")
        self.assertTrue(self.store.allowed("npub1aaa"))
        gate.deny("npub1aaa")
        self.assertFalse(self.store.allowed("npub1aaa"))
        self.assertTrue(self.store.denied("npub1aaa"))

    def test_no_acl_store_fails_closed(self):
        gate = FipsGate(self.fips)
        with self.assertRaises(AclError):
            gate.admit("npub1aaa")

    def test_pause_is_unsupported_in_strict_mode(self):
        gate = FipsGate(self.fips, self.store)
        with self.assertRaises(PauseUnsupported):
            gate.pause("npub1aaa")
        self.assertEqual(self.fips.disconnected, [])

    def test_crude_pause_disconnects_and_says_so(self):
        gate = FipsGate(self.fips, self.store, allow_disconnect=True)
        result = gate.pause("npub1aaa")
        self.assertFalse(result.paused)
        self.assertEqual(result.mode, "deny+disconnect")
        self.assertIn("payment lane", result.warning)
        self.assertTrue(self.store.denied("npub1aaa"))
        self.assertEqual(self.fips.disconnected, ["npub1aaa"])

    def test_durable_evict_requires_an_acl_store(self):
        gate = FipsGate(self.fips)
        with self.assertRaises(GateError):
            gate.evict("npub1aaa")

    def test_non_durable_evict_only_disconnects(self):
        gate = FipsGate(self.fips, self.store)
        result = gate.evict("npub1aaa", durable=False)
        self.assertEqual(result.mode, "disconnect")
        self.assertIsNone(result.acl_wait_ms)
        self.assertFalse(self.store.denied("npub1aaa"))
        self.assertEqual(self.fips.disconnected, ["npub1aaa"])

    def test_durable_evict_denies_before_disconnecting(self):
        gate = FipsGate(self.fips, self.store)
        gate.admit("npub1aaa")
        result = gate.evict("npub1aaa", durable=True)
        self.assertEqual(result.mode, "deny+disconnect")
        self.assertIsNotNone(result.acl_wait_ms)
        self.assertFalse(self.store.allowed("npub1aaa"))
        self.assertTrue(self.store.denied("npub1aaa"))
        self.assertEqual(self.fips.disconnected, ["npub1aaa"])

    def test_admit_sets_runtime_override_and_file(self):
        control = FakeControl()
        gate = FipsGate(self.fips, self.store, control=control)
        self.assertTrue(gate.admit("npub1aaa"))
        self.assertIn(("npub1aaa", "allow"), control.calls)
        self.assertTrue(self.store.allowed("npub1aaa"))

    def test_deny_sets_runtime_override_and_file(self):
        control = FakeControl()
        gate = FipsGate(self.fips, self.store, control=control)
        self.assertTrue(gate.deny("npub1aaa"))
        self.assertIn(("npub1aaa", "deny"), control.calls)
        self.assertTrue(self.store.denied("npub1aaa"))

    def test_evict_with_runtime_override_skips_acl_wait(self):
        control = FakeControl()
        gate = FipsGate(self.fips, self.store, control=control)
        result = gate.evict("npub1aaa")
        self.assertEqual(result.mode, "runtime+deny+disconnect")
        self.assertIsNone(result.acl_wait_ms)
        self.assertIn(("npub1aaa", "deny"), control.calls)
        self.assertTrue(self.store.denied("npub1aaa"))
        self.assertEqual(self.fips.disconnected, ["npub1aaa"])

    def test_evict_falls_back_to_acl_wait_without_control_command(self):
        gate = FipsGate(self.fips, self.store, control=FakeControl(fail=True))
        result = gate.evict("npub1aaa")
        self.assertEqual(result.mode, "deny+disconnect")
        self.assertIsNotNone(result.acl_wait_ms)
        self.assertTrue(self.store.denied("npub1aaa"))
        self.assertEqual(self.fips.disconnected, ["npub1aaa"])

    def test_pause_uses_patched_control_without_disconnect(self):
        control = FakeControl()
        gate = FipsGate(self.fips, self.store, control=control)
        result = gate.pause("npub1aaa")
        self.assertTrue(result.paused)
        self.assertEqual(result.mode, "transit-blocked")
        self.assertEqual(control.calls, [("npub1aaa", False)])
        self.assertEqual(self.fips.disconnected, [])

    def test_resume_uses_patched_control(self):
        control = FakeControl()
        gate = FipsGate(self.fips, self.store, control=control)
        gate.resume("npub1aaa")
        self.assertEqual(control.calls, [("npub1aaa", True)])

    def test_control_failure_strict_mode_raises(self):
        gate = FipsGate(self.fips, self.store, control=FakeControl(fail=True))
        with self.assertRaises(PauseUnsupported):
            gate.pause("npub1aaa")
        self.assertEqual(self.fips.disconnected, [])

    def test_control_failure_crude_mode_evicts(self):
        gate = FipsGate(self.fips, self.store, allow_disconnect=True,
                        control=FakeControl(fail=True))
        result = gate.pause("npub1aaa")
        self.assertEqual(result.mode, "deny+disconnect")
        self.assertTrue(self.store.denied("npub1aaa"))
        self.assertEqual(self.fips.disconnected, ["npub1aaa"])

    def test_resume_without_control_raises(self):
        gate = FipsGate(self.fips, self.store)
        with self.assertRaises(GateError):
            gate.resume("npub1aaa")

    def test_policy_blocked_passthrough(self):
        gate = FipsGate(self.fips, self.store)
        self.assertEqual(gate.policy_blocked(),
                         {"packets": 14, "bytes": 2063})

    def test_policy_blocked_for_passthrough(self):
        gate = FipsGate(self.fips, self.store)
        self.assertEqual(gate.policy_blocked_for("npub1aaa"),
                         {"peer": "peer-npub1aaa", "packets": 2, "bytes": 120})

    def test_meter_uses_previous_snapshot(self):
        gate = FipsGate(self.fips, self.store)
        previous = gate.counters()
        self.fips._peers[0]["stats"] = {
            "bytes_sent": 2500, "bytes_recv": 1200,
            "packets_sent": 25, "packets_recv": 12,
        }
        reading = gate.meter("npub1aaa", Decimal("1000"), previous=previous)
        self.assertEqual(reading.bytes_in, 200)
        self.assertEqual(reading.bytes_out, 500)
        self.assertEqual(reading.billable_bytes, 700)
        self.assertEqual(reading.cost_msat, Decimal("0.7"))

    def test_meter_unknown_peer(self):
        gate = FipsGate(self.fips, self.store)
        with self.assertRaises(PeerNotFound):
            gate.meter("npub1nope", Decimal("1000"))

    def test_snapshot_is_stable(self):
        self.assertEqual(snapshot(PEERS, LINKS), snapshot(PEERS, LINKS))


if __name__ == "__main__":
    unittest.main()
