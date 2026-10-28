"""First-login banner uses only attended, already-healthchecked credentials."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "bootstrap" / "show-first-login.py"
LAUNCH = ROOT / "bootstrap" / "single-controller.sh"
spec = importlib.util.spec_from_file_location("show_first_login", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

USER = "admin"
PASSWORD = "Correct16CharacterPassword2026"


def example_env(where: Path, extra: str = "") -> Path:
    path = where / "app.env"
    path.write_text(
        "# native AnsibleForms 7.4.2\n"
        f"ADMIN_USERNAME={USER}\n"
        f"ADMIN_PASSWORD={PASSWORD}\n"
        "DB_PASSWORD=never-expose-this\n"
        "RTE_TOKEN=never-expose-this-either\n" + extra
    )
    path.chmod(0o600)
    return path


class InitialLoginTests(unittest.TestCase):
    def test_reads_only_expected_login_without_leaking_database_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = example_env(Path(tmp))
            user, pwd = mod.read_initial_login(env, expected_root_uid=os.getuid())
            output = mod.render_login("192.0.2.100", user, pwd)
            self.assertIn("https://192.0.2.100/", output)
            self.assertIn("Benutzer: admin", output)
            self.assertIn("Passwort: " + PASSWORD, output)
            self.assertIn("JETZT ANMELDEN", output)
            self.assertNotIn("never-expose", output)
            self.assertIn("Passwort nach der ersten", output)

    def test_refuses_missing_or_duplicate_login_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = example_env(Path(tmp), "ADMIN_PASSWORD=second-value-not-allowed\n")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                mod.read_initial_login(env, expected_root_uid=os.getuid())
            env.write_text("ADMIN_USERNAME=admin\nDB_PASSWORD=secret\n")
            with self.assertRaises(ValueError):
                mod.read_initial_login(env, expected_root_uid=os.getuid())

    def test_rejects_unsafe_file_types_permissions_and_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = example_env(root)
            env.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "unsafe permissions"):
                mod.read_initial_login(env, expected_root_uid=os.getuid())
            env.chmod(0o600)
            second = root / "hardlink"
            os.link(env, second)
            with self.assertRaisesRegex(ValueError, "link count"):
                mod.read_initial_login(env, expected_root_uid=os.getuid())
            second.unlink()
            env.unlink()
            env.symlink_to(root / "missing-env")
            with self.assertRaises(ValueError):
                mod.read_initial_login(env, expected_root_uid=os.getuid())

    def test_never_renders_invalid_ip_or_secret_control_characters(self):
        for addr in ("127.0.0.1", "::1", "0.0.0.0", "224.0.0.1", "not-an-address"):
            with self.subTest(addr=addr), self.assertRaises(ValueError):
                mod.render_login(addr, USER, PASSWORD)
        with self.assertRaises(ValueError):
            mod.render_login("192.0.2.100", USER, "abc\nSECRET=LEAK")

    def test_final_output_after_health_and_no_secret_in_host_argv(self):
        src = LAUNCH.read_text()
        self.assertIn('show-first-login.py --ip "$IP"', src)
        self.assertIn('pct push "$VMID" "$ROOT/bootstrap/show-first-login.py"', src)
        self.assertIn('[[ -t 0 && -t 1 ]]', src)
        self.assertLess(src.index('systemctl is-active --quiet mariadb ansibleforms ansibleforms-rte'),
                        src.index('show-first-login.py --ip "$IP"'))
        self.assertLess(src.index("Checking AnsibleForms HTTPS localhost health"),
                        src.index('show-first-login.py --ip "$IP"'))
        self.assertNotIn("password printed by upstream installer above", src)
        self.assertNotIn("ADMIN_PASSWORD=", src)
        last = src.strip().splitlines()[-2:]
        self.assertIn('show-first-login.py --ip "$IP"', last[0])
        self.assertIn('First-login details unavailable', last[-1])

    def test_python_and_bash_syntax(self):
        out = subprocess.run(["bash", "-n", str(LAUNCH)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        out = subprocess.run([sys.executable, "-m", "py_compile", str(FILE)],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
