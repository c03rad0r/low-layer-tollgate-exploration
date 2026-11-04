import json
import unittest

from tollgate_fips.frame_gate import (
    FrameGate,
    FrameGateConfig,
    FrameGateError,
    normalise_mac,
)

MAC = "02:00:00:00:00:0a"
MAC_B = "02:00:00:00:00:0b"


class FakeNft:
    def __init__(self, output="{}"):
        self.output = output
        self.calls = []

    def run(self, args, check=True):
        self.calls.append((list(args), check))
        return self.output


def joined(calls):
    return [" ".join(args) for args, _ in calls]


class FrameGateTest(unittest.TestCase):
    def setUp(self):
        self.nft = FakeNft()
        self.gate = FrameGate(
            self.nft,
            FrameGateConfig(interface="eth9", rate_pps=777, burst=42,
                            timeout="5m"))

    def test_install_replaces_the_table_and_installs_the_rules(self):
        self.gate.install()
        calls = joined(self.nft.calls)
        self.assertIn("delete table netdev tollgate", calls)
        self.assertLess(calls.index("delete table netdev tollgate"),
                        calls.index("add table netdev tollgate"))
        rule_lines = [c for c in calls if c.startswith("add rule")]
        self.assertEqual(len(rule_lines), 3)  # blocked, bucket, accept
        self.assertIn("ether type 0x2121", rule_lines[0])
        self.assertIn("@blocked", rule_lines[0])
        self.assertIn("update @bucket", rule_lines[1])
        self.assertIn("limit rate over 777/second", rule_lines[1])
        self.assertIn("burst 42 packets", rule_lines[1])
        self.assertTrue(rule_lines[2].endswith("counter accept"))
        self.assertIn("device eth9", " ".join(calls))
        self.assertIn("timeout 5m", " ".join(calls))
        chain = next(c for c in calls if c.startswith("add chain"))
        self.assertTrue(chain.endswith("; }"))

    def test_default_deny_adds_an_allow_list_and_a_drop_rule(self):
        self.gate.config.default_deny = True
        self.gate.install()
        calls = joined(self.nft.calls)
        self.assertTrue(any("authorised" in c and c.startswith("add set")
                            for c in calls))
        rules = [c for c in calls if c.startswith("add rule")]
        self.assertEqual(len(rules), 4)  # blocked, allow-list, bucket, accept
        self.assertIn("!= @authorised", rules[1])
        self.assertIn("counter drop", rules[1])

    def test_install_is_idempotent(self):
        self.gate.install()
        first = len(self.nft.calls)
        self.gate.install()
        self.assertEqual(len(self.nft.calls), first * 2)

    def test_uninstall_deletes_the_table_without_checking(self):
        self.gate.uninstall()
        self.assertEqual(self.nft.calls, [(["delete", "table", "netdev",
                                            "tollgate"], False)])

    def test_authorise_blocks_and_resets_normalise_the_mac(self):
        self.gate.authorise("02-00-00-00-00-0A")
        self.gate.block(MAC_B)
        self.gate.reset_bucket(MAC_B)
        calls = joined(self.nft.calls)
        self.assertIn("add element netdev tollgate authorised { " + MAC + " }",
                      calls)
        self.assertIn("add element netdev tollgate blocked { " + MAC_B + " }",
                      calls)
        self.assertIn("delete element netdev tollgate bucket { " + MAC_B + " }",
                      calls)

    def test_deauthorise_and_unblock_tolerate_a_missing_element(self):
        self.gate.deauthorise(MAC)
        self.gate.unblock(MAC)
        self.assertEqual([check for _, check in self.nft.calls], [False, False])

    def test_invalid_mac_is_refused_before_any_command(self):
        for bad in ("02:00:00:00:00", "zz:00:00:00:00:00",
                    "02:00:00:00:00:00; drop"):
            with self.assertRaises(FrameGateError):
                self.gate.block(bad)
        self.assertEqual(self.nft.calls, [])

    def test_invalid_config_is_refused(self):
        cases = [
            {"interface": "eth0; drop"},
            {"table": "toll gate"},
            {"rate_pps": 0},
            {"burst": 0},
            {"timeout": "10 minutes"},
            {"ethertype": 0},
            {"max_entries": 0},
        ]
        for override in cases:
            config = FrameGateConfig(**override)
            with self.assertRaises(FrameGateError):
                config.validate()

    def test_status_parses_nft_json(self):
        status = {"nftables": [{"table": {"name": "tollgate"}}]}
        self.nft.output = json.dumps(status)
        self.assertEqual(self.gate.status(), status)
        self.assertEqual(
            self.nft.calls[-1][0],
            ["-j", "list", "table", "netdev", "tollgate"])

    def test_buckets_reads_the_real_nft_element_shape(self):
        self.nft.output = json.dumps({"nftables": [{"set": {
            "name": "bucket",
            "elem": [
                {"elem": {"val": MAC_B, "expires": 599,
                          "limit": {"rate": 1000, "burst": 100}}},
                {"elem": {"val": "02:00:00:00:00:0c", "expires": 598}},
            ],
        }}]})
        self.assertEqual(self.gate.buckets(), [MAC_B, "02:00:00:00:00:0c"])

    def test_normalise_mac_accepts_dashes_and_uppercase(self):
        self.assertEqual(normalise_mac("02-00-00-00-00-AB"),
                         "02:00:00:00:00:ab")


if __name__ == "__main__":
    unittest.main()
