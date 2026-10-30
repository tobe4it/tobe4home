"""Read-only bridge detection: do not infer VLAN purpose from bridge names."""
import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / "bootstrap" / "networks.py"
spec = importlib.util.spec_from_file_location("bootstrap_networks", FILE)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.links = [
            {"ifname": "vmbr0", "operstate": "UP", "flags": ["BROADCAST", "UP"],
             "linkinfo": {"info_kind": "bridge", "info_data": {"vlan_filtering": 0}}},
            {"ifname": "vmbr2", "operstate": "UP", "flags": ["BROADCAST", "UP"],
             "linkinfo": {"info_kind": "bridge", "info_data": {"vlan_filtering": 1}}},
            {"ifname": "fwbr100i0", "operstate": "UP",
             "linkinfo": {"info_kind": "bridge", "info_data": {"vlan_filtering": 1}}},
            {"ifname": "vmbr3", "operstate": "DOWN", "flags": ["BROADCAST"],
             "linkinfo": {"info_kind": "bridge", "info_data": {"vlan_filtering": 1}}},
        ]
        self.addresses = [{"ifname": "vmbr0", "addr_info": [
            {"family": "inet", "local": "192.0.2.10", "prefixlen": 24}]}]
        self.routes = [{"dst": "default", "dev": "vmbr0"}]
        self.bridges = network.analyze_bridges(self.links, self.addresses, self.routes)

    def test_only_real_proxmox_bridges(self):
        self.assertEqual([v["name"] for v in self.bridges], ["vmbr0", "vmbr2", "vmbr3"])
        self.assertTrue(self.bridges[0]["host_default_route"])
        self.assertTrue(self.bridges[1]["vlan_aware"])
        self.assertFalse(self.bridges[0]["vlan_aware"])

    def test_tagged_vlan_requires_aware_bridge(self):
        self.assertEqual(network.check_selection(self.bridges, "vmbr2", 42)["name"], "vmbr2")
        for bridge, tag in [("vmbr0", 42), ("vmbr2", 0),
                            ("vmbr2", 4095), ("vmbr3", 23), ("vmbr99", None)]:
            with self.subTest(bridge=bridge, tag=tag):
                with self.assertRaises(ValueError):
                    network.check_selection(self.bridges, bridge, tag)

    def test_untagged_is_explicitly_allowed(self):
        self.assertEqual(network.check_selection(self.bridges, "vmbr0", None)["name"], "vmbr0")

    def test_installer_does_not_force_manual_network_role_question(self):
        scripts = Path(__file__).resolve().parents[1] / "bootstrap"
        textui = (scripts / "installer-tui.sh").read_text()
        tui = (scripts / "launch.sh").read_text()
        self.assertIn('Schritt 4/5 – Bridge', textui)
        self.assertIn('INTERNEN Netzes', textui)
        self.assertNotIn('Schritt 4/5 – Netzwerkrolle', textui)
        self.assertNotIn('NETWORK_ROLE=', textui)
        self.assertNotIn('NETWORK_ROLE=', tui)


if __name__ == "__main__":
    unittest.main()
