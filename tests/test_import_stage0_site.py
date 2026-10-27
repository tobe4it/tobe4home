"""Check that Stage-0 migration only exports the expected nonsecret keys."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "bootstrap" / "import_stage0_site.py"
spec = importlib.util.spec_from_file_location("tb4h_import_stage0", MODULE)
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)


class ImportStage0Tests(unittest.TestCase):
    def test_import_only_nonsecret_fields(self):
        source = {"prefix": "tb4h", "dns_resolver": "192.0.2.53",
                  "password": "should-not-cross", "site_label": "private"}
        parsed = imp.produce(
            source, node="venombox", bridge="vmbr3", storage="local-zfs",
            template="local:vztmpl/rockylinux-10-default_20251001_amd64.tar.xz")
        self.assertEqual(set(parsed), {
            "prefix", "dns_resolver", "node", "bridge", "storage",
            "template", "vmid_from", "vmid_to"})
        self.assertNotIn("should-not-cross", str(parsed))
        self.assertEqual(parsed["vmid_from"], 1002)

    def test_invalid_dns_and_prefix(self):
        for dns in ("127.0.0.1", "::1", "0.0.0.0", "224.0.0.1"):
            with self.subTest(dns=dns), self.assertRaises(ValueError):
                imp.produce({"prefix": "tb4h", "dns_resolver": dns},
                            node="node", bridge="vmbr3", storage="zfs", template="test")
        with self.assertRaises(ValueError):
            imp.produce({"prefix": "../bad", "dns_resolver": "192.0.2.53"},
                        node="node", bridge="vmbr3", storage="zfs", template="test")

    def test_stage0_fetch_is_readonly_and_bounded(self):
        with patch.object(subprocess, "run") as run:
            run.return_value.stdout = '{"prefix":"tb4h","dns_resolver":"192.0.2.53"}'
            result = imp.stage0_config()
            args, kwargs = run.call_args
            self.assertEqual(args[0][:4], ["pct", "exec", "1000", "--"])
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 12)
            self.assertTrue(kwargs["check"])
            self.assertEqual(result["prefix"], "tb4h")


if __name__ == "__main__":
    unittest.main()
