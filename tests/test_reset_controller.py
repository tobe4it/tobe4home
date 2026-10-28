"""CT1001 clean-reset must require exact identity and confirmation."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESET = ROOT / "bootstrap" / "reset-controller.sh"
CHECK = ROOT / "bootstrap" / "check-controller-config.py"


class ResetControllerTests(unittest.TestCase):
    def test_help_can_be_read_without_proxmox(self):
        proc = subprocess.run(
            ["bash", str(RESET), "--help"], capture_output=True,
            text=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("READ-ONLY preview", proc.stdout)
        self.assertIn("DELETE 1001", proc.stdout)
        self.assertIn("no modification of CT1000", proc.stdout)

    def test_shell_syntax(self):
        proc = subprocess.run(
            ["bash", "-n", str(RESET)], capture_output=True,
            text=True, timeout=8)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_requires_identity_and_precheck_before_destroy(self):
        s = RESET.read_text()
        self.assertTrue(CHECK.exists())
        self.assertIn('python3 "$ROOT/bootstrap/check-controller-config.py" <<<"$cfg"', s)
        self.assertIn("Cluster membership of CT1001 is not verified", s)
        self.assertIn('pct status "$VMID"', s)
        self.assertIn("Type DELETE 1001", s)
        self.assertIn('pct destroy "$VMID"', s)
        self.assertLess(s.index("Type DELETE 1001"),
                        s.index('pct destroy "$VMID"'))
        self.assertLess(s.index("pct shutdown"),
                        s.index('pct destroy "$VMID"'))
        self.assertIn("inspect\npct destroy", s)
        self.assertIn("status: stopped", s)

    def test_no_force_no_purge_no_arbitrary_storage_wipe(self):
        s = RESET.read_text()
        self.assertNotIn("pct destroy 1000", s)
        self.assertNotIn('rm -rf /var/lib/lxc', s)
        self.assertNotIn('pct set ', s)
        self.assertNotIn('pvesm free ', s)
        self.assertNotIn('pct stop "$VMID"', s)
        self.assertNotIn('pct destroy "$VMID" --purge', s)
        self.assertNotIn('pct destroy "$VMID" --force', s)
        self.assertIn("no --destroy-unreferenced-disks", s)
        self.assertIn("Existing vzdump/PBS backups are not deleted", s)
        self.assertIn("Only CT1001 and its Proxmox-managed rootfs", s)

    def test_rejects_unmanaged_mounts_and_other_guest_changes(self):
        s = RESET.read_text()
        self.assertIn("Additional disk, mount, snapshot, lock or hook", s)
        self.assertIn("CT1001 has non-bootstrap settings", s)
        self.assertIn('"net0"', s)
        self.assertIn('"rootfs"', s)
        self.assertIn('"unprivileged"', s)
        self.assertNotIn('"mp0"', s)
        self.assertNotIn('"dev0"', s)


if __name__ == "__main__":
    unittest.main()
