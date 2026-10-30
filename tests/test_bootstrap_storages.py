"""Regression tests for Proxmox VE rootdir storage selection."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "bootstrap" / "storages.py"
spec = importlib.util.spec_from_file_location("bootstrap_storages", path)
storage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storage)

EXAMPLE = """Name             Type     Status     Total (KiB)      Used (KiB) Available (KiB) %
local-zfs        zfspool  active       1941464412      121410636     1820053776 6.25%
archive-zfs      zfspool  inactive              0              0              0 0.00%
"""

class TestStorageDetection(unittest.TestCase):
    def test_local_zfs_is_offered_and_inactive_excluded(self):
        self.assertEqual(storage.parse_rootdir_status(EXAMPLE), [
            {"name": "local-zfs", "type": "zfspool", "status": "active"}])

    def test_proxmox_content_filter_is_used(self):
        response = subprocess.CompletedProcess(
            ["pvesm", "status", "--content", "rootdir"],
            0, stdout=EXAMPLE, stderr="")
        with patch.object(storage.subprocess, "run", return_value=response) as run:
            self.assertEqual(storage.discover()[0]["name"], "local-zfs")
            run.assert_called_once_with(
                ["pvesm", "status", "--content", "rootdir"],
                capture_output=True, check=True, text=True)

    def test_no_rootdir_storage_is_not_silently_accepted(self):
        with patch.object(storage.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, stdout=EXAMPLE.replace("active ", "inactive "), stderr="")):
            with self.assertRaisesRegex(RuntimeError, "No active"):
                storage.discover()

    def test_invalid_status_header_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            storage.parse_rootdir_status("NAME TYPE STATUS\nlocal-zfs zfspool active\n")

    def test_installer_calls_supported_storage_discovery(self):
        script = (ROOT / "bootstrap" / "installer-tui.sh").read_text()
        self.assertIn('bootstrap/storages.py" --json', script)
        self.assertNotIn('pvesm config "$NAME"', script)

if __name__ == "__main__":
    unittest.main()
