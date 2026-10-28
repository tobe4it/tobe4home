"""Launcher must never launch obsolete two-LXC setup after ADR-001."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "bootstrap" / "launch.sh"


class SingleControllerLauncherGateTests(unittest.TestCase):
    def test_legacy_launcher_fails_closed_without_proxmox(self):
        run = subprocess.run(["bash", str(LAUNCH)], capture_output=True,
                             text=True, timeout=8)
        self.assertEqual(run.returncode, 3)
        self.assertIn("NO CONTAINER CREATED", run.stderr)
        self.assertIn("single-controller bootstrap", run.stderr.lower())
        self.assertIn("AnsibleForms/OpenTofu", run.stderr)
        self.assertNotIn("Created CT", run.stdout)

    def test_gate_precedes_any_legacy_actions(self):
        src = LAUNCH.read_text()
        self.assertLess(src.index("exit 3"), src.index('BOOTSTRAP="$ROOT/bootstrap/bootstrap.sh"'))
        self.assertLess(src.index("exit 3"), src.index('exec bash "$ROOT/bootstrap/installer-tui.sh"'))
        self.assertLess(src.index("exit 3"), src.index('bash "$BOOTSTRAP" "${ARGS[@]}" --apply'))
        run = subprocess.run(["bash", "-n", str(LAUNCH)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
