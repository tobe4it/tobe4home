"""Bootstrap compatibility report: no guest writes, no unsupported CPU guessing."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "bootstrap" / "host_preflight.py"
spec = importlib.util.spec_from_file_location("bootstrap_host_preflight", PATH)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class CompatibilityTests(unittest.TestCase):
    def test_cpu_feature_must_be_explicit(self):
        self.assertTrue(check.cpu_supported("x86-64-v3 (supported, searched)"))
        self.assertTrue(check.cpu_supported("x86-64-v3 (supported)"))
        self.assertFalse(check.cpu_supported("x86-64-v3 (unsupported)"))
        self.assertFalse(check.cpu_supported("avx2"))

    def test_storage_status_filter(self):
        status = "Name Type Status Total Used Available %\nlocal-zfs zfspool active 1 2 3 1%\narchive dir inactive 1 2 3 1%"
        self.assertEqual(check.parse_active_storages(status), {"local-zfs"})
        with self.assertRaises(ValueError):
            check.parse_active_storages("garbage")

    def test_zfs_pool_mapping(self):
        cfg = """dir: local
        path /var/lib/vz
        content iso,vztmpl

zfspool: local-zfs
        pool rpool/data
        content images,rootdir
        sparse 1

nfs: backup
        server 192.0.2.50
        export /x
"""
        self.assertEqual(check.zfs_pool_for_storage(cfg, "local-zfs"), "rpool/data")
        self.assertIsNone(check.zfs_pool_for_storage(cfg, "local"), )
        self.assertIsNone(check.zfs_pool_for_storage(cfg, "no-such-storage"))

    def test_readonly_compat_report_warns_about_zfs_limits(self):
        def fake_command(args):
            if args[0] == str(check.LOADER):
                return 0, "x86-64-v3 (supported, searched)"
            if args[:2] == ["pvesm", "status"]:
                return 0, "Name Type Status X Y Z Q\nlocal-zfs zfspool active 1 1 1 1%"
            if args[0] == "lxc-usernsexec":
                return 0, "0\n"
            return 0, "posixacl\n/rpool/data\noff\n"

        with patch.object(check, "command", side_effect=fake_command), \
                patch.object(check.platform, "machine", return_value="x86_64"), \
                patch.object(check.Path, "read_text", return_value="zfspool: local-zfs\n pool rpool/data\n"), \
                patch.object(check.Path, "exists", return_value=False):
            result = check.report("local-zfs", 1000)
        self.assertFalse(result["failures"])
        self.assertTrue(any("not prove new ZFS" in x for x in result["limitations"]))
        self.assertTrue(any(x["check"] == "Unprivileged LXC user namespace" for x in result["checks"]))

    def test_missing_v3_fails_closed(self):
        def fake(args):
            if args[0] == str(check.LOADER): return 0, "x86-64-v3 (unsupported)"
            if args[0] == "pvesm": return 0, "Name Type Status X\nlocal-zfs zfspool active 1"
            if args[0] == "lxc-usernsexec": return 0, "0"
            return 1, "no dataset"
        with patch.object(check, "command", side_effect=fake), \
                patch.object(check.platform, "machine", return_value="x86_64"), \
                patch.object(check.Path, "read_text", side_effect=OSError), \
                patch.object(check.Path, "exists", return_value=False):
            result = check.report("local-zfs", 1000)
        self.assertIn("Rocky Linux 10 x86-64-v3 CPU", result["failures"])

    def test_launcher_does_not_skip_preflight(self):
        script = (ROOT / "bootstrap" / "bootstrap.sh").read_text()
        self.assertIn('"$SCRIPT_DIR/host_preflight.py" --storage "$STORAGE" --vmid "$VMID"', script)
        self.assertIn('"https://" + ip + ":8765/health"', script)
        self.assertIn('https://$GUEST_IP:$PORT/', script)
        self.assertIn('SETUP CODE: $SETUP_CODE', script)
        self.assertIn('ssh-keygen -lf "$SSH_KEY"', script)
        self.assertNotIn('http://127.0.0.1:8765/health', script)


if __name__ == "__main__":
    unittest.main()
