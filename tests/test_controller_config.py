"""Proxmox-normalized LXC tags are unordered, never implicit ownership."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "bootstrap" / "check-controller-config.py"
SINGLE = ROOT / "bootstrap" / "single-controller.sh"

spec = importlib.util.spec_from_file_location("controller_config", CHECK)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

TEMPLATE = """arch: amd64
cores: 4
description: tobe4home single-controller test
hostname: tb4h-controller
memory: 4096
net0: name=eth0,bridge=vmbr3,firewall=1,ip=dhcp,type=veth
onboot: 0
ostype: centos
rootfs: local-zfs:subvol-1001-disk-0,size=40G
swap: 512
tags: {tags}
unprivileged: 1
"""


class ControllerConfigTests(unittest.TestCase):
    def test_pve_tag_sorting_and_original_order_both_accepted(self):
        for tags in ("tobe4home;controller", "controller;tobe4home",
                     "controller;review;tobe4home"):
            with self.subTest(tags=tags):
                checker.check_config(TEMPLATE.format(tags=tags))
                result = subprocess.run(
                    [sys.executable, str(CHECK)],
                    input=TEMPLATE.format(tags=tags), capture_output=True,
                    text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("CONTROLLER_IDENTITY_VERIFIED", result.stdout)

    def test_rejects_substring_tricks_and_ambiguous_tags(self):
        for tags in (
            "controller;tobe4home-other", "othercontroller;tobe4home",
            "controller", "tobe4home", "",
            "controller;tobe4home;controller",
            "controller;tobe4home;bad tag",
            "controller;tobe4home\nunprivileged: 0",
        ):
            with self.subTest(tags=tags), self.assertRaises(ValueError):
                checker.check_config(TEMPLATE.format(tags=tags))

    def test_refuses_foreign_or_privileged_container(self):
        good = TEMPLATE.format(tags="controller;tobe4home")
        for cfg in (
            good.replace("tb4h-controller", "tb4h-ansible"),
            good.replace("unprivileged: 1", "unprivileged: 0"),
            good.replace("rootfs: local-zfs:subvol-1001-disk-0,size=40G",
                         "rootfs: local-zfs:subvol-1000-disk-0,size=40G"),
            good.replace("rootfs: local-zfs:subvol-1001-disk-0,size=40G", ""),
            good.replace("tags: controller;tobe4home", "tags: unrelated"),
        ):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                checker.check_config(cfg)

    def test_no_duplicate_config_fields(self):
        good = TEMPLATE.format(tags="controller;tobe4home")
        for entry in ("tags: controller;tobe4home", "hostname: tb4h-controller",
                      "unprivileged: 1", "rootfs: local-zfs:subvol-1001-disk-0,size=40G"):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                checker.check_config(good + entry + "\n")

    def test_resume_runs_identity_check_before_confirmation_and_writes(self):
        src = SINGLE.read_text()
        self.assertIn('python3 "$ROOT/bootstrap/check-controller-config.py" <<< "$CFG"', src)
        self.assertNotIn("tobe4home.*controller", src)
        self.assertLess(src.index('check-controller-config.py" <<< "$CFG"'),
                        src.index("Type RESUME 1001"))
        self.assertLess(src.index("Type RESUME 1001"),
                        src.index("repair-ansibleforms-permissions.py --apply"))
        self.assertEqual(subprocess.run(
            ["bash", "-n", str(SINGLE)], capture_output=True, text=True,
            timeout=5).returncode, 0)


if __name__ == "__main__":
    unittest.main()
