"""Prove Proxmox census is host-read-only, bounded and privacy-minimal."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
COLLECT = ROOT / "bootstrap/collect-proxmox-inventory.py"
INSTALL = ROOT / "bootstrap/install-proxmox-snapshot.py"
RETROFIT = ROOT / "bootstrap/deploy-onboarding-1001.sh"
BOOTSTRAP = ROOT / "bootstrap/single-controller.sh"
FORM = ROOT / "ansibleforms/forms/tobe4home-start.yml"
PLAYBOOK = ROOT / "ansibleforms/playbooks/tb4h-onboarding-preview.yml"

def load(module_name, file):
    spec = importlib.util.spec_from_file_location(module_name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

collector = load("proxmox_collector", COLLECT)
installer = load("proxmox_snapshot_install", INSTALL)

PCT = """VMID       Status     Lock         Name
100        running                 bp-controller
126        running                 bergen-paperless
922        stopped                 bergen-mail-restoretest
1001       running                 tb4h-controller
"""
QM = """      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
       200 testvm               running    4096             50.00 500
       333 legacyvm             stopped    2048            100.00 0
"""

class ProxmoxDiscoveryTests(unittest.TestCase):
    def test_automatic_census_excludes_controller_and_identifying_details(self):
        result = collector.overview(PCT, QM, datetime(2026, 10, 28, 18, 0, tzinfo=timezone.utc))
        self.assertEqual(result["lxc"], {"total": 3, "running": 2})
        self.assertEqual(result["qemu"], {"total": 2, "running": 1})
        serialized = json.dumps(result)
        for secret in ("1001", "126", "bergen-paperless", "testvm", "192.168.", "token", "rootfs"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(result["source"], "proxmox-host-readonly")
        self.assertIn("2026-10-28", result["collected_at_utc"])
        installer.validate(serialized.encode())

    def test_empty_guest_hosts_are_not_conflated_with_failed_inventory(self):
        data = collector.overview("VMID Status Lock Name\n", "VMID NAME STATUS MEM(MB)\n")
        self.assertEqual(data["lxc"]["total"], 0)
        self.assertEqual(data["qemu"]["total"], 0)
        with self.assertRaises(ValueError):
            collector.overview("", "VMID NAME STATUS\n")

    def test_bad_status_and_duplicate_vmids_fail_closed(self):
        for raw in (
            "VMID Status Lock Name\n1 running\n1 stopped\n",
            "VMID Status Lock Name\n100 exploding\n",
            "VMID Status Lock Name\nx1 stopped\n",
            "unexpected header\n100 running\n",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                collector.parse_list(raw, "lxc")

    def test_no_guest_api_credential_or_live_scan_in_form_or_playbook(self):
        form = FORM.read_text()
        play = PLAYBOOK.read_text()
        self.assertNotIn("existing_services", form + play)
        self.assertNotIn("Laufen auf dem Server", form)
        self.assertEqual(form.count("    - subform:"), 2)
        self.assertIn("tb4h-proxmox-snapshot.json", play)
        self.assertIn("{{ playbook_dir }}/tb4h-proxmox-snapshot.json", play)
        self.assertNotIn("/opt/ansibleforms/data/playbooks/tb4h-proxmox-snapshot.json", play)
        self.assertIn("Die Proxmox-Bestandsaufnahme fehlt", play)
        self.assertNotIn("pvesh", play)
        self.assertNotIn("community.general.proxmox", play)
        self.assertNotIn("become:", play)

    def test_snapshot_rejects_untrusted_data(self):
        ok = collector.overview(PCT, QM)
        for changed in (
            {"extra": "credentials"},
            {"lxc": {"total": True, "running": 1}},
            {"lxc": {"total": 0, "running": 1}},
            {"source": "user-supplied"},
            {"collected_at_utc": "2026-10-28T18:00:00"},
            {"qemu": {"total": 40000, "running": 0}},
        ):
            bad = dict(ok)
            bad.update(changed)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                installer.validate(json.dumps(bad).encode())

    def test_idempotent_snapshot_refresh_and_local_symlink_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            folder = base / "playbooks"
            folder.mkdir()
            target = folder / "tb4h-proxmox-snapshot.json"
            source = base / "staged.json"
            first = collector.overview(PCT, QM)
            source.write_text(json.dumps(first))
            with patch.object(installer.os, "fchown"):
                self.assertEqual(installer.write_snapshot(source, target, os.getuid() or 1001, os.getgid() or 1001), "CREATED")
                self.assertEqual(installer.write_snapshot(source, target, 1001, 1001), "UNCHANGED")
                second = collector.overview("VMID Status Lock Name\n200 running test\n", QM)
                source.write_text(json.dumps(second))
                self.assertEqual(installer.write_snapshot(source, target, 1001, 1001), "UPDATED")
                self.assertEqual(json.loads(target.read_text()), second)
                target.unlink()
                target.symlink_to(source)
                with self.assertRaises(ValueError):
                    installer.write_snapshot(source, target, 1001, 1001)

    def test_native_and_retrofit_paths_both_run_readonly_host_scanner(self):
        for file in (BOOTSTRAP, RETROFIT):
            text = file.read_text()
            self.assertIn('python3 "$ROOT/bootstrap/collect-proxmox-inventory.py"', text)
            self.assertIn('install-proxmox-snapshot.py', text)
            self.assertIn('tb4h-proxmox-snapshot.json', text)
            self.assertLess(text.index('install-proxmox-snapshot.py ||'),
                            text.index('install-tobe4home-onboarding.py ||'),
                            "The preview must not be deployed before its data")
            self.assertNotIn("pct destroy", text)
            self.assertNotIn("pvesh set", text)
            r = subprocess.run(["bash", "-n", str(file)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        script = COLLECT.read_text()
        self.assertIn('("pct", "list")', script)
        self.assertIn('("qm", "list")', script)
        self.assertNotIn("shell=True", script)
        self.assertNotIn("pvesh", script)
        self.assertNotIn("pct exec", script)
        self.assertNotIn("qm agent", script)


if __name__ == "__main__":
    unittest.main()
