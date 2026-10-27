"""Verify AnsibleForms 7 preview YAML and its read-only Ansible runner."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "ansibleforms" / "forms" / "tobe4home-infra-preview.yml"
PLAYBOOK = ROOT / "ansibleforms" / "playbooks" / "tb4h-preview.yml"


class AnsibleFormsPreviewTests(unittest.TestCase):
    def test_two_page_wizard_with_preview_only_job(self):
        parsed = yaml.safe_load(FORM.read_text())
        self.assertIsInstance(parsed, list)
        forms = {x["name"]: x for x in parsed}
        self.assertEqual(len(forms), 3)
        main = forms["tobe4home – Infrastrukturplanung (Testvorschau)"]
        self.assertEqual(main["type"], "ansible")
        self.assertEqual(main["playbook"], "tb4h-preview.yml")
        self.assertEqual(len(main["wizard"]), 2)
        self.assertEqual(
            [x["subform"] for x in main["wizard"]],
            ["tb4h_services", "tb4h_runner"])
        self.assertEqual(
            {x["name"] for x in forms["tb4h_services"]["fields"]},
            {"git", "agent", "model"})
        self.assertEqual(
            [x["name"] for x in forms["tb4h_runner"]["fields"]],
            ["ci"])
        self.assertIn("Testformular ohne Proxmox-Schreibzugriff", main["help"])

    def test_playbook_is_local_read_only_and_has_no_elevated_privileges(self):
        playbooks = yaml.safe_load(PLAYBOOK.read_text())
        self.assertEqual(len(playbooks), 1)
        play = playbooks[0]
        self.assertEqual(play["hosts"], "localhost")
        self.assertFalse(play["gather_facts"])
        self.assertNotIn("become", play)
        serialized = str(play)
        self.assertIn("infra_planner.py", serialized)
        self.assertIn("inventory.example.json", serialized)
        self.assertIn("changed_when", serialized)
        for forbidden in ("proxmox_ve", "pct create", "tofu apply",
                          "become: true", "shell:", "script:"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
