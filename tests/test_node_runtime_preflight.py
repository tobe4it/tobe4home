"""The upstream AnsibleForms Node selection must not race missing artifacts."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootstrap" / "check-node-runtime.py"
SINGLE = ROOT / "bootstrap" / "single-controller.sh"
spec = importlib.util.spec_from_file_location("node_preflight", SCRIPT)
node = importlib.util.module_from_spec(spec)
spec.loader.exec_module(node)

INDEX = json.dumps([
    {"version": "v26.12.1", "files": ["linux-x64"]},
    {"version": "v26.13.0", "files": ["linux-x64"]},
    {"version": "v25.9.0", "files": ["linux-x64"]},
])
NAME = "node-v26.13.0-linux-x64.tar.gz"
SUMS = "a" * 64 + "  " + NAME + "\n"


class NodeArtifactPreflightTests(unittest.TestCase):
    def test_selects_semver_highest_even_if_index_unsorted(self):
        self.assertEqual(node.chosen_node_release(INDEX), "v26.13.0")
        self.assertEqual(
            node.chosen_node_release(json.dumps(
                [{"version": "v26.9.0"}, {"version": "v26.12.1"}])),
            "v26.12.1")
        self.assertEqual(node.chosen_node_release(INDEX, 25), "v25.9.0")

    def test_missing_checksum_in_latest_release_fails_not_fallback(self):
        with patch.object(node, "fetch_text") as fetch, patch.object(node, "check_asset") as asset:
            fetch.side_effect = [INDEX, FileNotFoundError("404 checksum")]
            with self.assertRaises(FileNotFoundError):
                node.check(26)
            asset.assert_not_called()
            self.assertEqual(fetch.call_args[0][0],
                             "https://nodejs.org/dist/v26.13.0/SHASUMS256.txt")

    def test_latest_release_must_list_the_exact_linux_x64_artifact(self):
        for bad in ("", "b" * 64 + "  node-v26.13.0-linux-arm64.tar.gz\n",
                    SUMS + SUMS, "sha256 only not valid\n"):
            with self.subTest(sums=bad[:15]):
                with patch.object(node, "fetch_text", side_effect=[INDEX, bad]):
                    with self.assertRaises(ValueError):
                        node.check(26)

    def test_verified_release_checks_official_archive(self):
        with patch.object(node, "fetch_text", side_effect=[INDEX, SUMS]) as fetch, \
             patch.object(node, "check_asset") as asset:
            self.assertEqual(node.check(26), "v26.13.0")
            asset.assert_called_once_with(
                "https://nodejs.org/dist/v26.13.0/" + NAME)
            self.assertEqual(fetch.call_count, 2)

    def test_host_gate_precedes_key_prompt_and_ct_create(self):
        src = SINGLE.read_text()
        self.assertIn('python3 "$ROOT/bootstrap/check-node-runtime.py" --major 26', src)
        self.assertIn('pct exec "$VMID" -- python3 /var/lib/tobe4home/check-node-runtime.py --major 26', src)
        self.assertLess(src.index('python3 "$ROOT/bootstrap/check-node-runtime.py" --major 26'),
                        src.index("SSH-Administrationsschlüssel aus bestehenden"))
        self.assertLess(src.index('python3 "$ROOT/bootstrap/check-node-runtime.py" --major 26'),
                        src.index('pct create "$VMID"'))
        self.assertLess(src.index('pct exec "$VMID" -- python3 /var/lib/tobe4home/check-node-runtime.py --major 26'),
                        src.index('pct exec "$VMID" -- bash /var/lib/tobe4home/install-ansibleforms-native.sh'))
        self.assertIn('--pinned v26.12.1', src)
        self.assertIn('die "Pinned Node.js v26.12.1 assets unavailable; no CT1001 created"', src)
        self.assertEqual(subprocess.run(["bash", "-n", str(SINGLE)]).returncode, 0)

    def test_rejects_bad_index_and_untrusted_url(self):
        for obj in ("{}", "[]", '[{"version":"v30.0.0"}]', "notjson"):
            with self.subTest(index=obj), self.assertRaises(ValueError):
                node.chosen_node_release(obj)
        with self.assertRaises(ValueError):
            node.verify_sums(SUMS, "node-v26.12.1-linux-x64.tar.gz")
        with self.assertRaises(ValueError):
            node.fetch_text("http://bad.test/dist/index.json", 300)

    def test_exact_pin_ignores_unavailable_latest_node_release(self):
        pinned_name = "node-v26.12.1-linux-x64.tar.gz"
        pinned_sums = "b" * 64 + "  " + pinned_name + "\\n"
        with patch.object(node, "fetch_text", return_value=pinned_sums) as fetch, \\
             patch.object(node, "check_asset") as asset:
            self.assertEqual(node.check(26, pinned="v26.12.1"), "v26.12.1")
            fetch.assert_called_once_with(
                "https://nodejs.org/dist/v26.12.1/SHASUMS256.txt", node.MAX_SUMS)
            asset.assert_called_once_with(
                "https://nodejs.org/dist/v26.12.1/" + pinned_name)

    def test_other_pin_refused_even_if_official_index_lists_it(self):
        with patch.object(node, "fetch_text") as fetch:
            with self.assertRaisesRegex(ValueError, "Only reviewed"):
                node.check(26, pinned="v26.13.0")
            fetch.assert_not_called()

    def test_cli_without_network_refuses_other_major(self):
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "--major", "24"],
            text=True, capture_output=True)
        self.assertEqual(p.returncode, 2)
        self.assertIn("NODE_PREFLIGHT_REFUSED", p.stderr)


if __name__ == "__main__":
    unittest.main()
