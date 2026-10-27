"""Non-privileged tests for the stage-0 installer wizard."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap" / "wizard.py"
spec = importlib.util.spec_from_file_location("wizard", SCRIPT)
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)

GOOD = {
    "site_label": "Demo Home",
    "base_domain": "home.example.org",
    "timezone": "Europe/Berlin",
    "dns_resolver": "192.0.2.53",
    "backup_kind": "nas",
}

class WizardTests(unittest.TestCase):
    def test_plan_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.local.json"
            wizard.save_plan(path, wizard.validate(GOOD))
            self.assertEqual(wizard.load_plan(path), GOOD)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('"deployment_enabled": false', path.read_text())

    def test_invalid_dns_and_domain(self):
        for k, value in (("dns_resolver", "not-an-ip"),
                         ("base_domain", "bad domain"),
                         ("backup_kind", "unverified")):
            with self.subTest(key=k):
                payload = dict(GOOD, **{k: value})
                with self.assertRaises(ValueError):
                    wizard.validate(payload)

    def test_output_escapes_rendered_input(self):
        payload = dict(GOOD, site_label='<script>alert(1)</script>')
        html = wizard.render(payload, "test-token")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_unauthorized_file_is_not_read_as_valid_site(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.local.json"
            path.write_text('{"site":{"site_label":"x"}}')
            self.assertEqual(wizard.load_plan(path), {})

    def test_all_prerequisites_are_present(self):
        names = [name for _, name, _ in wizard.PHASES]
        self.assertEqual(len(names), 7)
        self.assertIn("Recovery and backups", names)

if __name__ == "__main__":
    unittest.main()
