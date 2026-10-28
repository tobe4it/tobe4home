#!/usr/bin/env python3
"""Read-only compatibility diagnostics before installing a Rocky Linux 10 LXC.

This is an advisory host preflight, not a substitute for testing a real
unprivileged rootfs allocation. Never repairs mounts, ZFS, user maps or ACLs.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys

LOADER = Path("/lib64/ld-linux-x86-64.so.2")


def command(args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=12)
        return proc.returncode, proc.stdout + proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def cpu_supported(loader_output: str) -> bool:
    return bool(re.search(r"x86-64-v3\s+\(supported(?:,|\))", loader_output))


def parse_active_storages(output: str) -> set[str]:
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if not rows or rows[0][:3] != ["Name", "Type", "Status"]:
        raise ValueError("Unrecognized Proxmox storage status response")
    return {r[0] for r in rows[1:] if len(r) >= 3 and r[2] == "active"}


def zfs_pool_for_storage(cfg: str, storage: str) -> str | None:
    """Extract one zfspool pool name from Proxmox's storage.cfg without edits."""
    current = None
    storage_type = None
    for line in cfg.splitlines():
        m = re.fullmatch(r"(\w+):\s+(\S+)\s*", line)
        if m:
            storage_type, current = m.groups()
            continue
        if current == storage and storage_type == "zfspool":
            p = re.fullmatch(r"\s+pool\s+(\S+)\s*", line)
            if p:
                return p.group(1)
    return None


def classify_runtime_dir(path: Path) -> tuple[str, str]:
    """Inspect only; never remove existing Proxmox/LXC runtime data.

    An empty ordinary directory left after pct destroy may be removed with
    rmdir *after* explicit installation approval. Symlinks, files and
    nonempty directories are never treated as harmless remnants.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "PASS", "No existing LXC runtime path"
    except OSError as exc:
        return "FAIL", f"Cannot inspect runtime path: {exc.strerror}"
    if not stat.S_ISDIR(info.st_mode):
        return "FAIL", "Unexpected non-directory or symbolic link; inspect manually"
    try:
        with os.scandir(path) as entries:
            if next(entries, None) is not None:
                return "FAIL", "Nonempty LXC runtime directory; inspect contents, never remove recursively"
    except OSError as exc:
        return "FAIL", f"Cannot inspect LXC runtime contents: {exc.strerror}"
    return "WARN", "Empty LXC runtime directory; safe to rmdir only after guest creation approval"


def report(storage: str, vmid: int) -> dict:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    arch = platform.machine().lower()
    if arch not in {"x86_64", "amd64"}:
        add("Rocky Linux 10 CPU architecture", "FAIL", f"Unsupported architecture: {arch}")
    else:
        rc, output = command([str(LOADER), "--help"])
        if rc == 0 and cpu_supported(output):
            add("Rocky Linux 10 x86-64-v3 CPU", "PASS", "glibc loader reports supported")
        else:
            add("Rocky Linux 10 x86-64-v3 CPU", "FAIL",
                "CPU capability is absent or could not be verified using the glibc loader")

    rc, output = command(["pvesm", "status", "--content", "rootdir"])
    try:
        found = parse_active_storages(output) if rc == 0 else set()
    except ValueError:
        found = set()
    add("Rootfs storage available", "PASS" if storage in found else "FAIL",
        f"'{storage}' must be active and support rootdir")

    rc, output = command(["lxc-usernsexec", "-m", "u:0:100000:65536",
                          "-m", "g:0:100000:65536", "--", "id", "-u"])
    add("Unprivileged LXC user namespace", "PASS" if rc == 0 and output.strip() == "0" else "FAIL",
        "Tested isolated uid/gid mapping 0→100000 (not a rootfs write test)")

    ct_dir = Path(f"/var/lib/lxc/{vmid}")
    status, detail = classify_runtime_dir(ct_dir)
    add("Stale LXC directory", status, detail)
    # A failed pct create may remove the VMID config but leave a ZFS volume.
    # Read-only check; never delete volumes or reuse the name implicitly.
    rc, volumes = command(["pvesm", "list", storage, "--content", "rootdir"])
    volume_pattern = re.compile(rf"subvol-{vmid}-disk-[0-9]+")
    if rc != 0:
        add("Residual rootfs volumes", "WARN",
            "Could not list storage volumes; inspect manually before retrying")
    elif volume_pattern.search(volumes):
        add("Residual rootfs volumes", "FAIL",
            "Storage still contains a rootfs volume for this VMID; investigate first")
    else:
        add("Residual rootfs volumes", "PASS", "No matching rootdir volumes listed")

    cfg_path = Path("/etc/pve/storage.cfg")
    try:
        config = cfg_path.read_text(encoding="utf-8")
    except OSError:
        config = ""
    pool = zfs_pool_for_storage(config, storage)
    if pool:
        rc, zfs_out = command(["zfs", "get", "-H", "-o", "value",
                               "acltype,mountpoint,readonly", pool])
        if rc == 0:
            vals = zfs_out.strip().splitlines()
            if len(vals) == 3:
                acl, mountpoint, readonly = vals
                if readonly == "on":
                    add("ZFS rootfs pool writable", "FAIL",
                        f"Configured pool {pool} is read-only")
                else:
                    add("ZFS rootfs pool writable", "PASS", f"Configured pool: {pool}")
                add("ZFS ACL configuration", "WARN" if acl in {"off", "noacl"} else "PASS",
                    f"Pool {pool}: acltype={acl}; mountpoint={mountpoint}. "
                    "ACLs and uidmapped extraction are not fully tested.")
            else:
                add("ZFS properties", "WARN", f"Unexpected property response for {pool}")
        else:
            add("ZFS properties", "WARN", f"Unable to read ZFS properties for {pool}")
    else:
        add("Rootfs filesystem details", "WARN",
            "Could not map selected storage to a ZFS pool; uidmapped extraction unverified")

    return {"storage": storage, "vmid": vmid, "checks": checks,
            "failures": [c["check"] for c in checks if c["status"] == "FAIL"],
            "limitations": [
                "Read-only tests cannot prove new ZFS subvolume owner/ACL mapping.",
                "Guest DHCP, package mirrors and SSH reachability require real guest checks.",
            ]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--storage", required=True)
    parser.add_argument("--vmid", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = report(args.storage, args.vmid)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for c in result["checks"]:
            print(f'[{c["status"]}] {c["check"]}: {c["detail"]}')
        for limitation in result["limitations"]:
            print(f"[LIMIT] {limitation}")
    if result["failures"]:
        parser.exit(2, "ERROR: compatibility preflight rejected installation\n")


if __name__ == "__main__":
    main()
