"""Public SSH key reuse; ensure private identities and auth restrictions stay safe."""
import base64
import importlib.util
from pathlib import Path
import stat
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootstrap" / "ssh_keys.py"
spec = importlib.util.spec_from_file_location("bootstrap_ssh_keys", SCRIPT)
keys = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keys)


def sample_key(marker: int = 1) -> str:
    name = b"ssh-ed25519"
    pub = bytes([marker]) * 32
    blob = struct.pack(">I", len(name)) + name + struct.pack(">I", len(pub)) + pub
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii") + " admin@example.invalid"


class AdminKeyTests(unittest.TestCase):
    def test_extracts_real_login_keys_from_authorized_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            user = base / "lxadmin.authorized_keys"
            root = base / "root.authorized_keys"
            user.write_text("# authorized login keys\n" + sample_key(1) + "\n")
            root.write_text(sample_key(1) + "\n" + sample_key(2) + "\n")
            found = keys.discover_from_sources([("lxadmin", user), ("root", root)])
            self.assertEqual([x["source"] for x in found], ["lxadmin", "root"])
            self.assertEqual([x["index"] for x in found], ["1", "2"])
            self.assertTrue(found[0]["fingerprint"].startswith("SHA256:"))
            self.assertNotIn("admin@example.invalid", found[0]["key"])

    def test_restrictions_are_never_silently_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "authorized_keys"
            path.write_text('from="192.0.2.0/24" ' + sample_key(1) + "\n"
                            "restrict " + sample_key(2) + "\n")
            self.assertEqual(keys.discover_from_sources([("operator", path)]), [])

    def test_random_or_multiline_text_cannot_be_imported(self):
        for raw in ("", "-----BEGIN OPENSSH PRIVATE KEY-----",
                    "ssh-ed25519 ###", sample_key(1) + "\n" + sample_key(2),
                    "ssh-ed25519 YWFhYmJi"):
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(ValueError):
                    keys.normalized_key(raw)

    def test_export_is_single_public_key_line_and_private_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "admin.pub"
            fingerprint = keys.store_key(file, sample_key())
            self.assertTrue(fingerprint.startswith("SHA256:"))
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(file.read_text().count("\n"), 1)
            self.assertNotIn("admin@example.invalid", file.read_text())
            with self.assertRaises(FileExistsError):
                keys.store_key(file, sample_key(2))

    def test_unknown_fingerprint_rejected(self):
        with self.assertRaises(ValueError):
            keys.selected([], "SHA256:not-a-real-key")

    def test_host_identity_not_suggested_as_login_identity(self):
        source = SCRIPT.read_text()
        self.assertIn('".ssh" / "authorized_keys"', source)
        self.assertIn('Path("/root/.ssh/authorized_keys")', source)
        self.assertNotIn("id_rsa.pub", source)
        self.assertNotIn("id_ed25519.pub", source)

    def test_installer_stages_only_public_key(self):
        tui = (ROOT / "bootstrap" / "installer-tui.sh").read_text()
        cli = (ROOT / "bootstrap" / "single-controller.sh").read_text()
        self.assertIn('ssh_keys.py', tui)
        self.assertIn('"$KEY_HELPER" --list', tui)
        self.assertIn('"$KEY_HELPER" --export', tui)
        self.assertIn('trap \'rm -rf -- "$KEY_TEMP_DIR"\' EXIT', tui)
        self.assertIn('ssh_keys.py', cli)
        self.assertIn('"$KEY_HELPER" --interactive', cli)
        self.assertIn('trap \'rm -rf -- "$KEY_TEMP_DIR"\' EXIT', cli)


if __name__ == "__main__":
    unittest.main()
