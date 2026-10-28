"""Single-controller launcher must not reach legacy Stage-0 bootstraps."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "bootstrap" / "launch.sh"
SINGLE = ROOT / "bootstrap" / "single-controller.sh"
NATIVE = ROOT / "bootstrap" / "install-ansibleforms-native.sh"


class SingleControllerLauncherTests(unittest.TestCase):
    def test_launcher_delegates_only_to_single_controller(self):
        s = LAUNCH.read_text()
        self.assertIn('single-controller.sh', s)
        self.assertNotIn('bootstrap/bootstrap.sh', s)
        self.assertNotIn('installer-tui.sh', s)
        self.assertNotIn('deploy-ansible-controller.sh', s)

    def test_new_installer_help_on_non_proxmox_host(self):
        result = subprocess.run(["bash", str(LAUNCH), "--help"],
                                capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CT1001", result.stdout)
        self.assertIn("INSTALL 1001", result.stdout)
        self.assertIn("RESUME 1001", result.stdout)
        self.assertNotIn("CT1000 is created", result.stdout)

    def test_shell_syntax_of_new_install_path(self):
        for path in (LAUNCH, SINGLE, NATIVE):
            with self.subTest(path=path):
                proc = subprocess.run(["bash", "-n", str(path)],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_confirmation_before_any_new_guest_write(self):
        s = SINGLE.read_text()
        self.assertIn('Type INSTALL 1001', s)
        self.assertLess(s.index('Type INSTALL 1001'), s.index('pct create "$VMID"'))
        self.assertIn('pct start "$VMID"', s)
        self.assertIn('umask 022', s)
        self.assertIn('hostname tb4h-controller', s)
        self.assertIn('unprivileged 1', s)
        self.assertNotIn('pct create 1000', s)
        self.assertNotIn('pct destroy', s)
        self.assertNotIn('--privileged 1', s)


    def test_resume_repairs_existing_native_app_instead_of_reinstalling(self):
        single = SINGLE.read_text()
        repair = ROOT / "bootstrap" / "repair-ansibleforms-permissions.py"
        self.assertTrue(repair.exists())
        self.assertIn('pct push "$VMID" "$ROOT/bootstrap/repair-ansibleforms-permissions.py"', single)
        self.assertIn('test -f /etc/systemd/system/ansibleforms.service', single)
        self.assertIn('test -f /etc/systemd/system/ansibleforms-rte.service', single)
        self.assertIn('repair-ansibleforms-permissions.py --apply', single)
        self.assertIn('systemctl restart ansibleforms-rte ansibleforms', single)
        self.assertIn('curl -kfLsS --max-time 8', single)
        self.assertIn('pct exec "$VMID" -- systemctl is-active --quiet mariadb ansibleforms ansibleforms-rte', single)
        self.assertNotIn("chmod -R", single)
        self.assertNotIn("chown -R", single)
        self.assertLess(single.index("Type RESUME 1001"),
                        single.index('repair-ansibleforms-permissions.py --apply'))

    def test_native_installer_version_and_integrity_gate(self):
        src = NATIVE.read_text()
        self.assertIn("v7.4.2", src)
        self.assertIn("--version 7.4.2", src)
        self.assertIn("sha256sum --check", src)
        self.assertNotIn("curl | sh", src)
        self.assertIn("--mode native", src)
        self.assertNotIn("--runtime docker", src)
        self.assertNotIn("--runtime podman", src)


if __name__ == "__main__":
    unittest.main()
