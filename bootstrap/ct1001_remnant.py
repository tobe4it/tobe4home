#!/usr/bin/env python3
"""Quarantine only the exact CT1001 Proxmox runtime remnant after approval.

This is NOT a generic cleanup tool. Never deletes files, follows symlinks,
unmounts anything or touches a registered guest. Only an exact artifact set
is eligible: regular rules.seccomp and a completely empty passthrough dir.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
from datetime import datetime, timezone

CT_ID = 1001
RUNTIME = Path("/var/lib/lxc/1001")
QUARANTINE = Path("/var/lib/tobe4home/ct-runtime-quarantine")


def mount_points() -> list[str]:
    """Read actual kernel mounts, including bind mounts, without following links."""
    values = []
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Cannot inspect active mounts: {exc}") from exc
    for line in lines:
        fields = line.split()
        if len(fields) < 6:
            raise ValueError("Unexpected mountinfo entry")
        # Mountpoint fields use kernel octal escapes (\040 for spaces, etc).
        raw = fields[4]
        value = __import__("re").sub(
            r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), raw)
        values.append(value)
    return values


def mount_conflict(path: Path, mounts: list[str]) -> bool:
    prefix = str(path)
    return any(p == prefix or p.startswith(prefix + "/") for p in mounts)


def classify(path: Path, mounts: list[str] | None = None) -> tuple[str, str]:
    """Return PASS/SAFE_REMNANT/EMPTY/FAIL; classification never changes state."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "PASS", "No LXC runtime directory"
    except OSError:
        return "FAIL", "Cannot inspect LXC runtime directory"
    if not stat.S_ISDIR(info.st_mode):
        return "FAIL", "LXC runtime path is not a real directory"
    if mounts is None:
        try:
            mounts = mount_points()
        except ValueError as exc:
            return "FAIL", str(exc)
    if mount_conflict(path, mounts):
        return "FAIL", "Active mount at or below LXC runtime path"
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return "FAIL", "Cannot list LXC runtime directory"
    if not names:
        return "EMPTY", "Empty ordinary runtime directory"
    if names != ["passthrough", "rules.seccomp"]:
        return "FAIL", "Unexpected runtime entries: " + repr(names[:12])
    try:
        file_info = (path / "rules.seccomp").lstat()
        subdir_info = (path / "passthrough").lstat()
        if not stat.S_ISREG(file_info.st_mode):
            return "FAIL", "rules.seccomp is not a regular file"
        if not (0 < file_info.st_size <= 4096):
            return "FAIL", "Unexpected rules.seccomp size"
        if not stat.S_ISDIR(subdir_info.st_mode):
            return "FAIL", "passthrough is not a real directory"
        if os.listdir(path / "passthrough"):
            return "FAIL", "passthrough contains entries"
    except OSError:
        return "FAIL", "Cannot inspect expected runtime artifacts"
    return ("SAFE_REMNANT",
            "Only Proxmox rules.seccomp and empty passthrough remain; "
            "eligible for quarantining after explicit install approval")


def check_no_registered_guest() -> None:
    """Untrusted VMID cannot be retaken: check both local config and cluster."""
    cfg = subprocess.run(
        ["pct", "config", str(CT_ID)], capture_output=True, text=True,
        timeout=15, check=False)
    if cfg.returncode == 0:
        raise ValueError("CT1001 already registered in local Proxmox")
    # Any other error from pct config is ambiguous; distinguish with cluster.
    res = subprocess.run(
        ["pvesh", "get", "/cluster/resources", "--type", "vm",
         "--output-format", "json"], capture_output=True,
        text=True, timeout=20, check=True)
    import json
    records = json.loads(res.stdout)
    if not isinstance(records, list) or any(
        type(item.get("vmid")) is int and item["vmid"] == CT_ID
        for item in records if isinstance(item, dict)
    ):
        raise ValueError("CT1001 exists, or invalid cluster VMID inventory")


def quarantine(
    path: Path = RUNTIME,
    destination_root: Path = QUARANTINE,
    *,
    check_proxmox: bool = True,
    mounts: list[str] | None = None,
) -> Path:
    """Atomic rename only; preserves seccomp file and directory for review."""
    if check_proxmox:
        check_no_registered_guest()
    status, reason = classify(path, mounts)
    if status != "SAFE_REMNANT":
        raise ValueError(f"Remnant not eligible: {status} {reason}")
    if os.geteuid() != 0 and check_proxmox:
        raise ValueError("Requires root")
    for obj in (path, path / "rules.seccomp", path / "passthrough"):
        if obj.lstat().st_uid != os.geteuid():
            raise ValueError("Runtime remnant has unexpected ownership")
    # Parent is intentionally outside /var/lib/lxc to avoid Proxmox
    # discovering a pseudo-container under its runtime directory.
    destination_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination_root.is_symlink() or not destination_root.is_dir():
        raise ValueError("Quarantine location is not a real directory")
    dest_stat = destination_root.lstat()
    if dest_stat.st_uid != os.geteuid() or dest_stat.st_mode & 0o077:
        raise ValueError("Quarantine directory must be owned by operator and private")
    if path.stat().st_dev != dest_stat.st_dev:
        raise ValueError("Quarantine must be on the same filesystem (no copying)")
    # Check once more immediately before rename.
    if check_proxmox:
        check_no_registered_guest()
    status, reason = classify(path, mounts)
    if status != "SAFE_REMNANT":
        raise ValueError(f"Remnant changed: {status} {reason}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = destination_root / f"ct1001-{stamp}-{secrets.token_hex(6)}"
    if dest.exists() or dest.is_symlink():
        raise ValueError("Quarantine destination collision")
    os.rename(path, dest)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarantine-approved-ct1001", action="store_true")
    args = parser.parse_args()
    if not args.quarantine_approved_ct1001:
        parser.error("This tool only runs after exact INSTALL 1001 approval")
    if os.geteuid() != 0:
        parser.error("Proxmox root is required")
    try:
        location = quarantine()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"STOP: CT1001 quarantine refused: {exc}", file=sys.stderr)
        return 2
    print(f"CT1001_RUNTIME_QUARANTINED={location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
