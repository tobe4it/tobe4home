"""Retrofit must be separately approved and target only verified CT1001."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootstrap" / "deploy-onboarding-1001.sh"


class RetrofitTests(unittest.TestCase):
    def test_shell_syntax_and_approval(self):
        r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        src = SCRIPT.read_text()
        self.assertIn("ONBOARD 1001", src)
        self.assertIn('check-controller-config.py', src)
        self.assertLess(src.index("Type ONBOARD 1001"),
                        src.index('pct push 1001'))
        self.assertNotIn("pct destroy", src)
        self.assertNotIn("pct create", src)
        self.assertNotIn("rm -rf /var/lib/lxc", src)

    def test_no_admin_credentials_or_unbounded_proxmox_actions(self):
        src = SCRIPT.read_text()
        self.assertIn("TOBE4HOME_ONBOARDING_READY=YES", src)
        self.assertIn("/form/tobe4home-start", src)
        self.assertIn("systemctl restart ansibleforms", src)
        self.assertNotIn("PASSWORD=", src)
        self.assertNotIn("sshpass", src)
        self.assertNotIn("pvesh set", src)
        self.assertNotIn("pveum", src)


if __name__ == "__main__":
    unittest.main()
