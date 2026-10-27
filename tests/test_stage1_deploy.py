"""Review-only Stage-1 CT installer policy checks."""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap" / "deploy-ansible-controller.sh"


class Stage1InstallerTests(unittest.TestCase):
    def test_shell_syntax(self):
        run = subprocess.run(["bash", "-n", str(SCRIPT)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_create_is_gated_and_not_delete_capable(self):
        script = SCRIPT.read_text()
        self.assertIn("VMID=1001", script)
        self.assertIn("APPLY=0", script)
        self.assertIn('if (( ! APPLY )); then', script)
        self.assertIn('read -r -p "Type DEPLOY 1001', script)
        self.assertIn('[[ "$CONFIRM" == "DEPLOY 1001" ]]', script)
        self.assertIn('pct create "$VMID"', script)
        self.assertIn('--unprivileged 1 --onboot 0', script)
        self.assertIn('umask 022', script)
        self.assertIn('pvesh get /cluster/resources', script)
        self.assertIn('lxc-usernsexec', script)
        self.assertIn('pvesm status --content rootdir', script)
        self.assertIn('pct exec "$VMID" -- ansible --version', script)
        self.assertNotIn("pct destroy", script)
        self.assertNotIn("rm -rf", script)
        self.assertNotIn("--privileged 1", script)

    def test_no_implicit_network_or_storage_selection(self):
        script = SCRIPT.read_text()
        self.assertIn('BRIDGE=""', script)
        self.assertIn('STORAGE=""', script)
        self.assertIn("Missing/invalid --bridge", script)
        self.assertIn("Missing/invalid --storage", script)
        self.assertIn('[[ -d "/sys/class/net/$BRIDGE/bridge" ]]', script)
        self.assertIn('TEMPLATE="rockylinux-10-default_20251001_amd64.tar.xz"', script)


if __name__ == "__main__":
    unittest.main()
