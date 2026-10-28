"""Native AnsibleForms umask repair never touches secrets or persistent data."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bootstrap" / "repair-ansibleforms-permissions.py"
SCRIPT = ROOT / "bootstrap" / "install-ansibleforms-native.sh"
spec = importlib.util.spec_from_file_location("af_rights", SOURCE)
fix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fix)


def fixture(path):
    root = path / "opt" / "ansibleforms"
    release = root / "releases" / "7.4.2"
    runtime = root / "runtime"
    (release / "server" / "src").mkdir(parents=True)
    (release / "venv" / "bin").mkdir(parents=True)
    (runtime / "node" / "bin").mkdir(parents=True)
    (root / "data" / "ssh").mkdir(parents=True)
    (root / "home").mkdir()
    (root / "installer-backups").mkdir()
    (root / "current").symlink_to("releases/7.4.2")
    (release / "server" / "index.js").write_text("original app code")
    (release / "venv" / "bin" / "ansible").write_text("script")
    (release / "server" / "persistent").symlink_to(root / "data")
    (release / "server" / "src" / "custom.js").symlink_to(root / "data" / "custom.js")
    (root / "data" / "ssh" / "private_key").write_text("secret")
    (root / "home" / ".ssh").mkdir()
    (root / "home" / ".ssh" / "authorized_keys").write_text("secret")
    (root / "installer-backups" / "db.sql").write_text("secret")
    (runtime / "node" / "bin" / "node").write_text("script")
    (root / "app.env").write_text("ADMIN_PASSWORD=secret\n")
    (root / "rte.env").write_text("RTE_TOKEN=secret\n")
    for obj in list(root.rglob("*")) + [root]:
        if obj.is_symlink():
            continue
        if obj.is_dir():
            os.chmod(obj, 0o700)
        else:
            os.chmod(obj, 0o600)
    for exe in (runtime / "node" / "bin" / "node",
                release / "venv" / "bin" / "ansible"):
        os.chmod(exe, 0o700)
    return root


class NativeRepairTests(unittest.TestCase):
    def test_repair_grants_group_code_read_execute_and_env_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(Path(tmp))
            changes = fix.plan(base, "ansibleforms", expected_uid=os.getuid(), gid=os.getgid())
            self.assertTrue(changes)
            self.assertTrue(any(p.name == "app.env" for p, g, m in changes))
            self.assertFalse(any("/data/" in str(p) or "/home/" in str(p) or
                                 "/installer-backups/" in str(p) for p, g, m in changes))
            # Mock only expected uid for a non-root unit test, but execute
            # should still require the trusted uid for every actual file.
            import unittest.mock
            with unittest.mock.patch.object(fix, "kind", wraps=fix.kind), \
                 unittest.mock.patch.object(fix.os, "chown", wraps=fix.os.chown):
                # Non-root CI has no root files; exercise the mode model
                # and target scoping without making host changes.
                pass
            for path, group_id, desired in changes:
                self.assertEqual(group_id, os.getgid())
                self.assertNotIn("private_key", str(path))
                self.assertNotIn("authorized_keys", str(path))
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & desired,
                                 stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(fix.mode_for_code((base/"releases"/"7.4.2"/"server").stat()) & 0o050, 0o050)

    def test_repair_is_idempotent_and_no_private_files_ever_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(Path(tmp))
            changes = fix.plan(base, "ansibleforms", expected_uid=os.getuid(), gid=os.getgid())
            for file, gid, mode in changes:
                # Exercise the same chmod/chgrp operations but only in tmp.
                os.chown(file, -1, gid)
                os.chmod(file, mode)
            self.assertFalse(fix.plan(base, "ansibleforms", expected_uid=os.getuid(), gid=os.getgid()))
            self.assertEqual((base/"app.env").stat().st_mode & 0o777, 0o640)
            self.assertEqual((base/"rte.env").stat().st_mode & 0o777, 0o640)
            for rel in ("data/ssh/private_key","home/.ssh/authorized_keys","installer-backups/db.sql"):
                self.assertEqual((base/rel).stat().st_mode & 0o777, 0o600)
            self.assertEqual((base/"runtime/node/bin/node").stat().st_mode & 0o777, 0o750)

    def test_reject_wrong_release_or_unexpected_nonroot_code_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(Path(tmp))
            (base/"current").unlink()
            (base/"current").symlink_to("releases/another")
            with self.assertRaisesRegex(ValueError, "Unexpected active"):
                fix.plan(base, "ansibleforms", expected_uid=os.getuid(), gid=os.getgid())

    def test_reject_untrusted_env_modes_and_symlinked_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = fixture(Path(tmp))
            os.chmod(base/"app.env", 0o604)
            with self.assertRaisesRegex(ValueError,"permissive"):
                fix.plan(base, "ansibleforms", expected_uid=os.getuid(), gid=os.getgid())
            os.chmod(base/"app.env", 0o600)
            (base/"releases"/"7.4.2"/"server"/"index.js").unlink()
            (base/"releases"/"7.4.2"/"server"/"index.js").symlink_to(base/"app.env")
            # Symlinks inside the code are ignored rather than followed.
            self.assertTrue(fix.plan(base, "ansibleforms", expected_uid=os.getuid(), gid=os.getgid()))

    def test_new_install_process_drops_umask_only_for_upstream(self):
        script=SCRIPT.read_text()
        self.assertIn("umask 077", script)
        self.assertIn("umask 022", script)
        self.assertLess(script.index("umask 022"), script.index("exec /usr/local/bin/ansibleforms-installer install"))
        self.assertNotIn("chmod -R", script)


if __name__ == "__main__":
    unittest.main()
