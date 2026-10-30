"""Contract tests for the read-only infrastructure plan compiler."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MOD_PATH = Path(__file__).resolve().parents[1] / "bootstrap" / "infra_planner.py"
spec = importlib.util.spec_from_file_location("infra_planner", MOD_PATH)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def fixtures():
    site = {
        "prefix": "tb4h", "node": "venombox", "storage": "local-zfs",
        "bridge": "vmbr3",
        "template": "local:vztmpl/rockylinux-10-default_20251001_amd64.tar.xz",
        "dns_resolver": "192.0.2.2", "vmid_from": 1002, "vmid_to": 1099,
    }
    choices = {
        "git": "new", "agent": "new", "model": "existing", "ci": "new",
    }
    inventory = {
        "node": "venombox", "vmids": [1000, 1001, 1004],
        "bridges": ["vmbr3"], "templates": [site["template"]],
        "storages": {
            "local-zfs": {"active": True, "content": ["rootdir", "images"],
                          "free_gb": 180}
        },
        "free_mb": 20_000, "cores_available": 16,
        "existing_services": {
            "model": {"verified": True, "endpoint": "https://models.example.invalid"}
        },
    }
    return site, choices, inventory


class PlannerTests(unittest.TestCase):
    def test_selects_only_needed_guests_and_skips_taken_vmids(self):
        site, choices, inventory = fixtures()
        plan = planner.compile_plan(site, choices, inventory)
        self.assertEqual([g["role"] for g in plan["guests"]], ["git", "agent", "ci"])
        self.assertEqual([g["vmid"] for g in plan["guests"]], [1002, 1003, 1005])
        self.assertEqual(plan["existing_services"]["model"],
                         "https://models.example.invalid")
        self.assertEqual(plan["totals"]["new_guests"], 3)
        self.assertFalse(plan["approved"])
        self.assertTrue(all(g["unprivileged"] and not g["started"]
                            for g in plan["guests"]))
        self.assertTrue(all(g["firewall"] for g in plan["guests"]))

    def test_hash_deterministic_and_sensitive_to_choice(self):
        site, choices, inventory = fixtures()
        a = planner.compile_plan(site, choices, inventory)
        b = planner.compile_plan(site, choices, inventory)
        self.assertEqual(a, b)
        inventory["existing_services"]["git"] = {
            "verified": True, "endpoint": "https://git.example.invalid"}
        choices["git"] = "existing"
        c = planner.compile_plan(site, choices, inventory)
        self.assertNotEqual(a["plan_sha256"], c["plan_sha256"])
        self.assertEqual([g["role"] for g in c["guests"]], ["agent", "ci"])

    def test_existing_must_be_verified(self):
        site, choices, inventory = fixtures()
        choices["git"] = "existing"
        for value in (
            None, {}, {"verified": False, "endpoint": "https://git.invalid"},
            {"verified": True, "endpoint": "http://git.invalid"},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inventory["existing_services"]["git"] = value
                planner.compile_plan(site, choices, inventory)

    def test_fail_closed_on_capacity_and_vmids(self):
        site, choices, inventory = fixtures()
        inventory["free_mb"] = 1000
        with self.assertRaisesRegex(ValueError, "memory"):
            planner.compile_plan(site, choices, inventory)
        site, choices, inventory = fixtures()
        inventory["storages"]["local-zfs"]["free_gb"] = 10
        with self.assertRaisesRegex(ValueError, "storage"):
            planner.compile_plan(site, choices, inventory)
        site, choices, inventory = fixtures()
        site["vmid_from"] = 1004
        site["vmid_to"] = 1005
        with self.assertRaisesRegex(ValueError, "exhausted"):
            planner.compile_plan(site, choices, inventory)

    def test_disallows_unverified_storage_network_template_and_host(self):
        tests = ["bridge", "template", "storage", "node"]
        for field in tests:
            site, choices, inventory = fixtures()
            site[field] = "unverified"
            with self.subTest(field=field), self.assertRaises(ValueError):
                planner.compile_plan(site, choices, inventory)

    def test_no_secrets_or_unsafe_identifiers(self):
        for field, value in (
            ("bridge", "vmbr3;rm -rf /"),
            ("storage", 'pool"}\nresource "evil"'),
            ("prefix", "../../foo"),
            ("dns_resolver", "127.0.0.1"),
        ):
            site, choices, inventory = fixtures()
            site[field] = value
            if field == "dns_resolver":
                # Loopback is syntactically IPv4 but may not resolve outside
                # a custom guest; guard such values separately in planner.
                pass
            else:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    planner.compile_plan(site, choices, inventory)
        site, choices, inventory = fixtures()
        site["proxmox_api_token"] = "do-not-store"
        with self.assertRaisesRegex(ValueError, "credentials"):
            planner.compile_plan(site, choices, inventory)
        site, choices, inventory = fixtures()
        choices["git"] = "omit"
        with self.assertRaisesRegex(ValueError, "mandatory"):
            planner.compile_plan(site, choices, inventory)

    def test_hcl_preview_disables_start_prevents_destroy_and_no_creds(self):
        site, choices, inventory = fixtures()
        plan = planner.compile_plan(site, choices, inventory)
        hcl = planner.render_opentofu(plan)
        self.assertEqual(hcl.count('resource "proxmox_virtual_environment_container"'), 3)
        self.assertEqual(hcl.count("prevent_destroy = true"), 3)
        self.assertEqual(hcl.count("unprivileged = true"), 3)
        self.assertEqual(hcl.count("started      = false"), 3)
        self.assertIn('version = "= 0.118.0"', hcl)
        self.assertIn('type = "centos"', hcl)
        self.assertIn("plan_sha256: " + plan["plan_sha256"], hcl)
        self.assertNotIn("api_token", hcl)
        self.assertNotIn("root@pam", hcl)
        self.assertNotIn("destroy", hcl.replace("prevent_destroy", ""))

    def test_html_topology_escapes_untrusted_inventory(self):
        site, choices, inventory = fixtures()
        plan = planner.compile_plan(site, choices, inventory)
        rendered = planner.render_html(plan)
        self.assertIn("VORSCHAU", rendered)
        self.assertIn("CT 1002", rendered)
        self.assertIn("plan", rendered.lower())
        self.assertIn(plan["plan_sha256"], rendered)
        self.assertNotIn("<script", rendered.lower())
        plan["existing_services"]["model"] = 'https://example.invalid/"><script>alert(1)</script>'
        safe = planner.render_html(plan)
        self.assertNotIn("<script>", safe)
        self.assertIn("&lt;script&gt;", safe)

    def test_rejects_loopback_dns_and_url_credentials(self):
        site, choices, inventory = fixtures()
        site["dns_resolver"] = "127.0.0.1"
        with self.assertRaises(ValueError):
            planner.compile_plan(site, choices, inventory)
        site, choices, inventory = fixtures()
        inventory["existing_services"]["model"]["endpoint"] = (
            "https://user:password@models.example.invalid/?api_token=abc")
        with self.assertRaises(ValueError):
            planner.compile_plan(site, choices, inventory)

    def test_cli_json_preview_and_tf_preview(self):
        site, choices, inventory = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n, data in (("site", site), ("choices", choices),
                            ("inventory", inventory)):
                (root / (n + ".json")).write_text(json.dumps(data))
            args = [sys.executable, str(MOD_PATH),
                    "--site", str(root / "site.json"),
                    "--choices", str(root / "choices.json"),
                    "--inventory", str(root / "inventory.json")]
            cmd = subprocess.run(args, capture_output=True, text=True, check=True)
            data = json.loads(cmd.stdout)
            self.assertEqual(data["totals"]["new_guests"], 3)
            txt = subprocess.run(args + ["--tf"], capture_output=True,
                                 text=True, check=True)
            self.assertIn("proxmox_virtual_environment_container", txt.stdout)
            self.assertNotIn("api_token =", txt.stdout)
            html = subprocess.run(args + ["--html"], capture_output=True,
                                  text=True, check=True)
            self.assertIn("<!doctype html>", html.stdout)
            self.assertIn(data["plan_sha256"], html.stdout)
            self.assertEqual(sorted(x.name for x in root.iterdir()),
                             ["choices.json", "inventory.json", "site.json"])


if __name__ == "__main__":
    unittest.main()
