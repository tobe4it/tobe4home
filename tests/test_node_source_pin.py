"""Audited Go-source patch modifies only Node version selection."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "bootstrap" / "patch-node-pin.py"
BUILD = ROOT / "bootstrap" / "build-native-installer.sh"
INSTALL = ROOT / "bootstrap" / "install-ansibleforms-native.sh"
spec = importlib.util.spec_from_file_location("node_source_pin", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ORIGINAL = """package native
import (
  "fmt"
  "os"
)
func installNode(ctx context.Context, l layout, major string) (string, error) {
    base := "https://nodejs.org/dist/" + version + "/"
    if err := fetchSum(ctx, base+name+".tar.gz", sum, tmp, 1); err != nil { return "", err }
}
func latestNode(ctx context.Context, major string) (string, error) {
\tindex, err := getText(ctx, "https://nodejs.org/dist/index.json")
\treturn "unused", err
}
"""


class NodeSourcePatchTests(unittest.TestCase):
    def test_audited_patch_removes_index_lookup_when_pin_set(self):
        out = mod.patch_source(ORIGINAL)
        self.assertEqual(out.count("TOBE4HOME_NODE_VERSION"), 1)
        self.assertIn('if pin != "v26.12.1" || major != "26"', out)
        self.assertIn("return pin, nil", out)
        self.assertEqual(out.count('fetchSum(ctx, base+name+".tar.gz", sum, tmp, 1)'), 1)
        self.assertEqual(out.count("https://nodejs.org/dist/index.json"), 1)
        self.assertTrue(out.startswith(ORIGINAL[:15]))
        self.assertNotEqual(out, ORIGINAL)

    def test_rejects_unexpected_or_already_patched_source(self):
        for source in (
            ORIGINAL.replace("getText(", "getBody("),
            ORIGINAL + ORIGINAL,
            ORIGINAL.replace('"os"', '"no_os"'),
            ORIGINAL.replace('fetchSum(ctx, base+name+".tar.gz", sum, tmp, 1)',
                             'fetchWithoutCheck()'),
            mod.patch_source(ORIGINAL),
        ):
            with self.subTest(source=source[:24]), self.assertRaises(ValueError):
                mod.patch_source(source)

    def test_patcher_operates_on_only_named_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "native" / "native.go"
            path.parent.mkdir()
            path.write_text(ORIGINAL)
            proc = subprocess.run(
                [sys.executable, str(FILE), str(path)],
                capture_output=True, text=True, timeout=8)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("ANSIBLEFORMS_NODE_PIN_APPLIED=v26.12.1", proc.stdout)
            proc2 = subprocess.run(
                [sys.executable, str(FILE), str(path)],
                capture_output=True, text=True, timeout=8)
            self.assertNotEqual(proc2.returncode, 0)
            self.assertIn("INSTALLER_NODE_PATCH_REFUSED", proc2.stderr)

    def test_source_provenance_and_compiler_are_exact(self):
        src = BUILD.read_text()
        native = INSTALL.read_text()
        self.assertIn("ae60b31742ee5bd6956f9bf9798fd5b5356ccf42", src)
        self.assertIn('refs/tags/v7.4.2', src)
        self.assertIn('"$ACTUAL_COMMIT" == "$EXPECTED_COMMIT"', src)
        self.assertIn('GOTOOLCHAIN=go1.27.2', src)
        self.assertIn('GOSUMDB=sum.golang.org', src)
        self.assertIn('GOFLAGS=-mod=readonly', src)
        self.assertIn('go build -trimpath -buildvcs=false', src)
        self.assertIn('bash /var/lib/tobe4home/build-native-installer.sh', native)
        self.assertIn("TOBE4HOME_NODE_VERSION=v26.12.1", native)
        self.assertNotIn("SHASUMS256.txt: not found", src)
        for bash in (BUILD, INSTALL):
            with self.subTest(bash=bash):
                proc = subprocess.run(["bash", "-n", str(bash)],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
