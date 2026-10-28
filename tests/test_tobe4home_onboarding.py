"""Prove the novice onboarding flow is real, bounded, and safe on resume."""
from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootstrap" / "install-tobe4home-onboarding.py"
MAIN = ROOT / "bootstrap" / "single-controller.sh"
FORM = ROOT / "ansibleforms" / "forms" / "tobe4home-start.yml"
PLAYBOOK = ROOT / "ansibleforms" / "playbooks" / "tb4h-onboarding-preview.yml"
BANNER = ROOT / "bootstrap" / "show-first-login.py"
spec = importlib.util.spec_from_file_location("tb4h_onboard", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class BeginnerOnboardingTests(unittest.TestCase):
    def test_wizard_is_in_german_with_no_proxmox_or_admin_secrets(self):
        forms = yaml.safe_load(FORM.read_text())
        self.assertEqual(len(forms), 4)
        first = forms[0]
        self.assertEqual(first["name"], "tobe4home Start")
        self.assertEqual(first["type"], "ansible")
        self.assertEqual(first["playbook"], PLAYBOOK.name)
        self.assertIn("Willkommen", first["help"])
        self.assertIn("noch nicht implementiert", first["help"])
        self.assertEqual(len(first["wizard"]), 3)
        self.assertEqual(len({f["name"] for f in forms}), 4)
        for subform in forms[1:]:
            self.assertEqual(subform["type"], "subform")
            for field in subform["fields"]:
                self.assertEqual(field["type"], "enum")
                self.assertTrue(field["required"])
                self.assertEqual(field["valueColumn"], "id")
                self.assertEqual(field["previewColumn"], "text")
                self.assertEqual(field["columns"], ["text"])
                self.assertIn(field["default"], [v["id"] for v in field["values"]])
                self.assertTrue(all(v["text"] for v in field["values"]))
        self.assertNotIn("password", FORM.read_text().lower())
        self.assertNotIn("token", FORM.read_text().lower())

    def test_job_has_no_privileged_or_write_operations(self):
        plays = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(plays), 1)
        play = plays[0]
        self.assertEqual(play["hosts"], "localhost")
        self.assertFalse(play["gather_facts"])
        self.assertEqual(play["connection"], "local")
        for task in play["tasks"]:
            self.assertNotIn("become", task)
            self.assertTrue(set(task.keys()) & {"ansible.builtin.assert", "ansible.builtin.debug"})
            self.assertFalse(task.get("changed_when", True))
        for forbidden in ("pct create", "community.general", "command:", "shell:",
                          "ansible.builtin.copy", "ansible.builtin.file", "tofu apply"):
            self.assertNotIn(forbidden, PLAYBOOK.read_text().lower())

    def test_installer_is_idempotent_and_refuses_modified_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            stage.mkdir()
            data = Path(tmp) / "data"
            data.mkdir()
            (stage / "tobe4home-start.yml").write_bytes(FORM.read_bytes())
            (stage / "tb4h-onboarding-preview.yml").write_bytes(PLAYBOOK.read_bytes())
            # CI may not run as root, chown to own user is a harmless no-op.
            with patch.object(mod.os, "fchown"):
                first = mod.deploy(stage, data, os.getuid() or 1001, os.getgid() or 1001)
                self.assertEqual(set(first.values()), {"CREATED"})
                second = mod.deploy(stage, data, os.getuid() or 1001, os.getgid() or 1001)
                self.assertEqual(set(second.values()), {"UNCHANGED"})
                existing = data / "forms" / "tobe4home-start.yml"
                existing.write_text("operator change")
                with self.assertRaisesRegex(ValueError, "refusing replacement"):
                    mod.deploy(stage, data, os.getuid() or 1001, os.getgid() or 1001)
                self.assertEqual(existing.read_text(), "operator change")

    def test_symlink_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            source = Path(tmp) / "input"
            source.write_text("some checked onboarding content")
            target.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "Unexpected target file type"):
                mod.install_asset(source, target, 1001, 1001)

    def test_bootstrap_installs_form_before_health_and_password_panel(self):
        src = MAIN.read_text()
        self.assertIn("install-tobe4home-onboarding.py", src)
        self.assertIn('pct push "$VMID" "$ROOT/ansibleforms/forms/tobe4home-start.yml"', src)
        self.assertIn('pct push "$VMID" "$ROOT/ansibleforms/playbooks/tb4h-onboarding-preview.yml"', src)
        self.assertLess(
            src.index('install-tobe4home-onboarding.py ||'),
            src.index('systemctl is-active --quiet mariadb ansibleforms ansibleforms-rte'))
        self.assertLess(
            src.index('install-tobe4home-onboarding.py ||'),
            src.index('show-first-login.py --ip "$IP"'))
        banner = BANNER.read_text()
        self.assertIn("/form/tobe4home-start", banner)
        self.assertIn('Passwort: {password}', banner)

    def test_form_playbook_is_syntax_valid(self):
        proc = subprocess.run(
            [sys.executable, "-m", "py_compile", str(SCRIPT)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
