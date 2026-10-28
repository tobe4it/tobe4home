"""Safe repeat-install behavior for stale Proxmox /var/lib/lxc/<vmid>."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "bootstrap" / "host_preflight.py"
SINGLE = ROOT / "bootstrap" / "single-controller.sh"
spec = importlib.util.spec_from_file_location("host_preflight_remnant", PREFLIGHT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RuntimeDirectoryTests(unittest.TestCase):
    def test_absent_directory_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "1001"
            self.assertEqual(mod.classify_runtime_dir(candidate)[0], "PASS")
            self.assertFalse(candidate.exists())

    def test_empty_directory_warns_but_does_not_remove_it(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "1001"
            candidate.mkdir()
            status, detail = mod.classify_runtime_dir(candidate)
            self.assertEqual(status, "WARN")
            self.assertIn("rmdir", detail)
            self.assertTrue(candidate.is_dir())

    def test_nonempty_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "1001"
            candidate.mkdir()
            (candidate / "rootfs").mkdir()
            status, detail = mod.classify_runtime_dir(candidate)
            self.assertEqual(status, "FAIL")
            self.assertIn("'rootfs' (directory)", detail)
            self.assertTrue((candidate / "rootfs").is_dir())
            (candidate / "rootfs").rmdir()
            (candidate / "config").write_text("untrusted")
            self.assertEqual(mod.classify_runtime_dir(candidate)[0], "FAIL")
            self.assertEqual((candidate / "config").read_text(), "untrusted")

    def test_summarizes_entries_without_reading_private_content(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate = Path(temp) / "1001"
            candidate.mkdir()
            (candidate / "rootfs").mkdir()
            (candidate / "config").write_text("super-secret-do-not-display")
            status, detail = mod.classify_runtime_dir(candidate)
            self.assertEqual(status, "FAIL")
            self.assertIn("'config' (file)", detail)
            self.assertIn("'rootfs' (directory)", detail)
            self.assertNotIn("super-secret-do-not-display", detail)

    def test_symlink_and_regular_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            target = base / "real"
            target.mkdir()
            link = base / "1001"
            link.symlink_to(target, target_is_directory=True)
            self.assertEqual(mod.classify_runtime_dir(link)[0], "FAIL")
            self.assertTrue(link.is_symlink())
            link.unlink()
            link.write_text("do not modify")
            self.assertEqual(mod.classify_runtime_dir(link)[0], "FAIL")
            self.assertEqual(link.read_text(), "do not modify")

    def test_install_script_uses_only_rmdir_after_confirmation(self):
        src = SINGLE.read_text()
        self.assertIn("rmdir -- /var/lib/lxc/1001", src)
        self.assertNotIn("rm -rf /var/lib/lxc", src)
        self.assertLess(src.index('host_preflight.py" --storage'),
                        src.index('python3 "$KEY_HELPER" --interactive'))
        self.assertLess(src.index("Type INSTALL 1001"),
                        src.index("rmdir -- /var/lib/lxc/1001"))
        self.assertLess(src.index("rmdir -- /var/lib/lxc/1001"),
                        src.index('pct create "$VMID"'))
        self.assertIn("CT1001 leftover not empty", src)
        self.assertEqual(subprocess.run(
            ["bash", "-n", str(SINGLE)], capture_output=True, text=True
        ).returncode, 0)


if __name__ == "__main__":
    unittest.main()
