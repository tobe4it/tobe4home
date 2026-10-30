"""The service planner is an intake-only, no-execution CT1001 retrofit."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import hashlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / "ansibleforms/forms/tobe4home-service-plan.yml"
PLAY = ROOT / "ansibleforms/playbooks/tb4h-service-plan-preview.yml"
INSTALL = ROOT / "bootstrap/install-tobe4home-planner.py"
DEPLOY = ROOT / "bootstrap/deploy-service-planner-1001.sh"
ORIGINAL_FORM = ROOT / "tests/fixtures/tobe4home-service-plan-v1.yml"
spec = importlib.util.spec_from_file_location("tb4h_service_planner", INSTALL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ServicePlannerTests(unittest.TestCase):
    def test_form_is_german_and_uses_guarded_local_playbook(self):
        forms = yaml.safe_load(FORM.read_text(encoding="utf-8"))
        self.assertEqual(len(forms), 1)
        form = forms[0]
        self.assertEqual(form["playbook"], PLAY.name)
        self.assertEqual(form["name"], "tobe4home Dienstplanung")
        self.assertFalse(form["allowJinjaInExtravars"])
        self.assertIn("noch kein KI-Chat", form["help"])
        fields = {f["name"]: f for f in form["fields"]}
        self.assertEqual(set(fields), {"service_kind", "request_text", "access_scope"})
        self.assertEqual(fields["request_text"]["type"], "textarea")
        # AnsibleForms 7.4.2 forbids minLength/maxLength on a textarea.
        self.assertFalse({"minLength", "maxLength", "regex"} & set(fields["request_text"]))
        self.assertIn("request_text | length <= 1600", PLAY.read_text())
        self.assertIn("request_text | length >= 15", PLAY.read_text())
        self.assertEqual({x["id"] for x in fields["service_kind"]["values"]},
                         {"paperless", "dns_filter", "proxy", "mailserver"})

    def test_playbook_can_never_deploy_or_echo_request_text(self):
        content = PLAY.read_text(encoding="utf-8")
        plays = yaml.safe_load(content)
        self.assertEqual(len(plays), 1)
        p = plays[0]
        self.assertEqual(p["hosts"], "localhost")
        self.assertEqual(p["connection"], "local")
        self.assertFalse(p["gather_facts"])
        permitted = {"ansible.builtin.assert", "ansible.builtin.stat",
                     "ansible.builtin.set_fact", "ansible.builtin.debug"}
        for task in p["tasks"]:
            self.assertFalse(task.get("changed_when", True))
            self.assertNotIn("become", task)
            actions = {k for k in task if k.startswith("ansible.builtin.")}
            self.assertTrue(actions)
            self.assertTrue(actions <= permitted, actions)
        for forbidden in ("pct create", "pct destroy", "tofu apply", "ansible.builtin.shell:",
                          "ansible.builtin.command:", "ansible.builtin.copy:",
                          "ansible.builtin.file:", "ansible.builtin.template:"):
            self.assertNotIn(forbidden, content.lower())
        self.assertNotIn("request_text }}", content)
        self.assertIn("request_text | hash('sha256')", content)
        self.assertIn("tb4h-proxmox-snapshot.json", content)
        self.assertIn("ansible.builtin.fail:", content)  # Inert YAML string ONLY
        self.assertNotIn("ansible.builtin.fail", {
            action for task in p["tasks"] for action in task if action.startswith("ansible.builtin.")
        })

    def test_retrofit_requires_approval_and_never_resets(self):
        result = subprocess.run(["bash", "-n", str(DEPLOY)],
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        script = DEPLOY.read_text(encoding="utf-8")
        self.assertIn("PLAN 1001", script)
        self.assertIn("check-controller-config.py", script)
        self.assertLess(script.index("Type PLAN 1001"), script.index("pct push 1001"))
        self.assertIn("PREVIEW_ONLY=YES", script)
        self.assertIn("PROXMOX_CHANGES=0", script)
        self.assertNotIn("pct create", script)
        self.assertNotIn("pct destroy", script)
        self.assertNotIn("rm -rf", script)
        self.assertNotIn("pveum", script)
        self.assertNotIn("app.env", script)

    def test_asset_install_is_idempotent_and_refuses_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            data = root / "data"
            stage.mkdir()
            data.mkdir()
            (data / "forms").mkdir()
            (data / "playbooks").mkdir()
            uid = os.getuid() or 65534
            gid = os.getgid() or 65534
            if os.geteuid() == 0:
                for folder in (data, data / "forms", data / "playbooks"):
                    os.chown(folder, uid, gid)
            (stage / FORM.name).write_bytes(FORM.read_bytes())
            (stage / PLAY.name).write_bytes(PLAY.read_bytes())
            first = module.install(stage, data, uid=uid, gid=gid)
            self.assertEqual(set(first.values()), {"CREATED"})
            second = module.install(stage, data, uid=uid, gid=gid)
            self.assertEqual(set(second.values()), {"UNCHANGED"})
            target = data / "forms" / FORM.name
            target.write_text("operator changed this form and it must not be replaced")
            with self.assertRaisesRegex(ValueError, "operator-modified"):
                module.install(stage, data, uid=uid, gid=gid)
            self.assertIn("operator changed", target.read_text())

    def test_exact_original_form_can_upgrade_without_replacing_user_edits(self):
        prior = ORIGINAL_FORM.read_bytes()
        sha = hashlib.sha1(b"blob " + str(len(prior)).encode() + b"\x00" + prior,
                           usedforsecurity=False).hexdigest()
        self.assertEqual(sha, "214c02698a2ea0650551317c97eee6681df62b4a")
        self.assertTrue(module.approved_prior(FORM.name, prior))
        self.assertFalse(module.approved_prior(PLAY.name, prior))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage, data = root / "stage", root / "data"
            stage.mkdir()
            data.mkdir()
            (data / "forms").mkdir()
            (data / "playbooks").mkdir()
            uid, gid = os.getuid() or 65534, os.getgid() or 65534
            if os.geteuid() == 0:
                for folder in (data, data / "forms", data / "playbooks"):
                    os.chown(folder, uid, gid)
            (stage / FORM.name).write_bytes(FORM.read_bytes())
            (stage / PLAY.name).write_bytes(PLAY.read_bytes())
            old_path = data / "forms" / FORM.name
            old_path.write_bytes(prior)
            if os.geteuid() == 0:
                os.chown(old_path, uid, gid)
            result = module.install(stage, data, uid=uid, gid=gid)
            self.assertEqual(result[FORM.name], "UPDATED")
            self.assertEqual(result[PLAY.name], "CREATED")
            self.assertEqual(old_path.read_bytes(), FORM.read_bytes())
            self.assertEqual(module.install(stage, data, uid=uid, gid=gid)[FORM.name],
                             "UNCHANGED")
            old_path.write_bytes(prior + b"\\n# site operator edit\\n")
            with self.assertRaisesRegex(ValueError, "operator-modified"):
                module.install(stage, data, uid=uid, gid=gid)

    def test_symlink_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            data = root / "data"
            stage.mkdir()
            data.mkdir()
            (data / "forms").mkdir()
            (data / "playbooks").mkdir()
            uid = os.getuid() or 65534
            gid = os.getgid() or 65534
            if os.geteuid() == 0:
                for folder in (data, data / "forms", data / "playbooks"):
                    os.chown(folder, uid, gid)
            (stage / FORM.name).write_bytes(FORM.read_bytes())
            (stage / PLAY.name).write_bytes(PLAY.read_bytes())
            target = data / "forms" / FORM.name
            target.symlink_to(stage / FORM.name)
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                module.install(stage, data, uid=uid, gid=gid)
            self.assertFalse((data / "playbooks" / PLAY.name).exists())


if __name__ == "__main__":
    unittest.main()
