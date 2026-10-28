"""CT1001 nonempty Proxmox runtime remnant: safe quarantine contracts."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bootstrap" / "ct1001_remnant.py"
PREFLIGHT = ROOT / "bootstrap" / "host_preflight.py"
spec = importlib.util.spec_from_file_location("ct1001_remnant", SOURCE)
remnant = importlib.util.module_from_spec(spec)
spec.loader.exec_module(remnant)


def create_remnant(base):
    path = base / "1001"
    path.mkdir()
    (path / "passthrough").mkdir()
    (path / "rules.seccomp").write_text("2\nblacklist\nmknod errno 0\n")
    return path


class QuarantineTests(unittest.TestCase):
    def test_exact_proxmox_remnant_is_safe_for_explicit_quarantine_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = create_remnant(Path(tmp))
            state, reason = remnant.classify(path, [])
            self.assertEqual(state, "SAFE_REMNANT", reason)
            self.assertIn("explicit install approval", reason)
            self.assertTrue((path / "rules.seccomp").is_file())

    def test_quarantine_renames_whole_tree_preserving_seccomp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_remnant(root)
            dest_root = root / "private"
            dest = remnant.quarantine(path, dest_root, check_proxmox=False, mounts=[])
            self.assertFalse(path.exists())
            self.assertEqual((dest / "rules.seccomp").read_text(),
                             "2\nblacklist\nmknod errno 0\n")
            self.assertTrue((dest / "passthrough").is_dir())
            self.assertEqual(list((dest / "passthrough").iterdir()), [])
            self.assertEqual(stat.S_IMODE(dest_root.stat().st_mode), 0o700)

    def test_mount_points_block_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_remnant(root)
            self.assertEqual(remnant.classify(path, [str(path)])[0], "FAIL")
            self.assertEqual(
                remnant.classify(path, [str(path / "passthrough")])[0], "FAIL")
            with self.assertRaisesRegex(ValueError, "not eligible"):
                remnant.quarantine(path, root / "dest",
                                   check_proxmox=False,
                                   mounts=[str(path / "passthrough")])
            self.assertTrue(path.exists())

    def test_unexpected_additional_entry_disables_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_remnant(root)
            (path / "config").write_text("private: never display this content")
            state, detail = remnant.classify(path, [])
            self.assertEqual(state, "FAIL")
            self.assertNotIn("private: never display", detail)
            with self.assertRaises(ValueError):
                remnant.quarantine(path, root / "dest",
                                   check_proxmox=False, mounts=[])
            self.assertTrue((path / "config").exists())

    def test_symlinks_and_nonempty_passthrough_disable_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_remnant(root)
            (path / "passthrough" / "mounts").write_text("do not touch")
            self.assertEqual(remnant.classify(path, [])[0], "FAIL")
            (path / "passthrough" / "mounts").unlink()
            (path / "rules.seccomp").unlink()
            (path / "rules.seccomp").symlink_to("/etc/passwd")
            self.assertEqual(remnant.classify(path, [])[0], "FAIL")

    def test_quarantine_does_not_follow_symlinked_destination_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_remnant(root)
            real = root / "real"
            real.mkdir()
            link = root / "redirect"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError):
                remnant.quarantine(path, link / "quarantine",
                                   check_proxmox=False, mounts=[])
            self.assertTrue(path.exists())

    def test_bootstrap_orders_checks_and_approval_before_quarantine(self):
        source = (ROOT / "bootstrap" / "single-controller.sh").read_text()
        self.assertIn("--quarantine-approved-ct1001", source)
        self.assertIn('pct config "$VMID"', source)
        self.assertIn('ROOTDIR_VOLUMES="$(pvesm list', source)
        self.assertLess(source.index("Type INSTALL 1001"),
                        source.index("python3 \"$ROOT/bootstrap/ct1001_remnant.py\""))
        self.assertLess(source.index("python3 \"$ROOT/bootstrap/ct1001_remnant.py\""),
                        source.index('pct create "$VMID"'))
        self.assertNotIn("rm -rf /var/lib/lxc/1001", source)

    def test_preflight_warns_for_exact_remnant(self):
        spec = importlib.util.spec_from_file_location("host_preflight_quarantine", PREFLIGHT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            path = create_remnant(Path(tmp))
            status, description = mod.classify_runtime_dir(path)
            self.assertEqual(status, "WARN", description)
            self.assertIn("quarantining", description)

    def test_any_other_vmid_requires_an_independent_decision(self):
        source = PREFLIGHT.read_text()
        self.assertIn("vmid != 1001", source)

    def test_cluster_occupancy_blocks_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = create_remnant(root)
            with patch.object(remnant, "check_no_registered_guest",
                              side_effect=ValueError("occupied")):
                with self.assertRaisesRegex(ValueError, "occupied"):
                    remnant.quarantine(path, root / "private",
                                       check_proxmox=True, mounts=[])
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
