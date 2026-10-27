"""Bounded PVE read-only discovery tests with synthetic API payloads."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "bootstrap" / "pve_snapshot.py"
spec = importlib.util.spec_from_file_location("pve_snapshot", PATH)
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def payload(path, *params):
    if path == "/cluster/resources":
        return [{"vmid": 1000}, {"vmid": 1001}, {"vmid": 1001},
                {"vmid": 800}, {"id": "node"}]
    if path == "/nodes/venombox/network":
        return [{"iface": "vmbr0", "type": "bridge", "active": 1},
                {"iface": "vmbr3", "type": "bridge", "active": 1},
                {"iface": "eth0", "type": "eth", "active": 1},
                {"iface": "vmbr2", "type": "bridge", "active": 0}]
    if path == "/nodes/venombox/storage":
        return [{"storage": "local-zfs", "active": 1,
                 "content": "rootdir,images", "avail": 100 * 1024**3},
                {"storage": "local", "active": 1,
                 "content": "vztmpl,backup", "avail": 20 * 1024**3}]
    if path == "/nodes/venombox/status":
        return {"memory": {"free": 12 * 1024**3},
                "cpuinfo": {"cpus": 8}}
    if path == "/nodes/venombox/storage/local/content":
        return [{"volid": "local:vztmpl/rockylinux-10-default_20251001_amd64.tar.xz"},
                {"volid": "other:vztmpl/example.tar.gz"}]
    raise AssertionError(f"unexpected API call {path!r}")


class SnapshotTests(unittest.TestCase):
    def test_exports_limited_nonsecret_metadata(self):
        with patch.object(snapshot, "pvesh", side_effect=payload) as get:
            data = snapshot.export("venombox", "local")
        self.assertEqual(data["vmids"], [800, 1000, 1001])
        self.assertEqual(data["bridges"], ["vmbr0", "vmbr3"])
        self.assertEqual(data["free_mb"], 12 * 1024)
        self.assertEqual(data["cores_available"], 8)
        self.assertEqual(data["storages"]["local-zfs"]["free_gb"], 100)
        self.assertEqual(len(data["templates"]), 1)
        self.assertEqual(data["existing_services"], {})
        self.assertEqual(get.call_count, 5)
        self.assertNotIn("token", json.dumps(data).lower())

    def test_refuses_malformed_node_and_template_storage(self):
        for node in ("../escape", "a;b", "", "venombox/example", "a\nb"):
            with self.subTest(node=node), self.assertRaises(ValueError):
                snapshot.export(node, "local")
        with self.assertRaises(ValueError):
            snapshot.export("venombox", "local?content=secret")

    def test_refuses_untrusted_available_capacity(self):
        def broken(path, *args):
            data = payload(path, *args)
            if path == "/nodes/venombox/status":
                data["memory"]["free"] = None
            return data
        with patch.object(snapshot, "pvesh", side_effect=broken):
            with self.assertRaisesRegex(ValueError, "free RAM"):
                snapshot.export("venombox", "local")

    def test_pvesh_uses_get_only_and_separate_argv(self):
        with patch.object(snapshot.subprocess, "run") as run:
            run.return_value.stdout = "[]"
            snapshot.pvesh("/cluster/resources", "--type", "vm")
            args, kwargs = run.call_args
            self.assertEqual(args[0][:3],
                             ["pvesh", "get", "/cluster/resources"])
            self.assertNotIn("shell", kwargs)
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["timeout"], 18)


if __name__ == "__main__":
    unittest.main()
