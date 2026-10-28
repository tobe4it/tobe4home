#!/usr/bin/env python3
"""Deploy a bounded read-only Proxmox guest-count snapshot in AnsibleForms.

Only accepts a strict, privacy-minimal JSON contract staged by the host.
Never runs Proxmox commands inside CT1001. Safely updates this one file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile
from datetime import datetime

SOURCE = Path("/var/lib/tobe4home/tb4h-proxmox-snapshot.json")
FOLDER = Path("/opt/ansibleforms/data/playbooks")
DEST = FOLDER / "tb4h-proxmox-snapshot.json"
EXPECTED_KEYS = frozenset({"schema", "source", "collected_at_utc", "lxc", "qemu", "note"})
NOTE = "Nur Proxmox-Gäste, keine Erkennung von Anwendungen in den Gästen"


def read_regular_file(path: Path) -> bytes:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not 50 <= st.st_size <= 4096:
        raise ValueError("Unexpected snapshot file type or size")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(fd, "rb") as handle:
            return handle.read(4097)
    finally:
        pass


def validate(raw: bytes) -> dict:
    if not 50 <= len(raw) <= 4096:
        raise ValueError("Invalid inventory size")
    try:
        info = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid JSON inventory") from exc
    if not isinstance(info, dict) or frozenset(info) != EXPECTED_KEYS:
        raise ValueError("Unexpected inventory JSON keys")
    if type(info["schema"]) is not int or info["schema"] != 1:
        raise ValueError("Unsupported inventory schema")
    if info["source"] != "proxmox-host-readonly" or info["note"] != NOTE:
        raise ValueError("Untrusted inventory origin or scope")
    try:
        timestamp = datetime.fromisoformat(info["collected_at_utc"])
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid snapshot timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("Snapshot timestamp must be UTC")
    for kind in ("lxc", "qemu"):
        counts = info[kind]
        if not isinstance(counts, dict) or set(counts) != {"total", "running"}:
            raise ValueError(f"Invalid {kind} counters")
        total, running = counts["total"], counts["running"]
        if type(total) is not int or type(running) is not int:
            raise ValueError("Inventory counters must be integers")
        if not 0 <= running <= total <= 2000:
            raise ValueError("Invalid guest counts")
    return info


def write_snapshot(source: Path = SOURCE, target: Path = DEST, uid: int | None = None,
                   gid: int | None = None) -> str:
    if uid is None or gid is None:
        acc = pwd.getpwnam("ansibleforms")
        uid, gid = acc.pw_uid, acc.pw_gid
    if uid == 0 or gid == 0:
        raise ValueError("Snapshot must be owned by unprivileged AnsibleForms user")
    folder = target.parent
    st = folder.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise ValueError("Invalid AnsibleForms playbook directory")
    if st.st_uid not in (0, uid) or st.st_mode & 0o002:
        raise ValueError("Unexpected AnsibleForms playbook directory owner or permissions")
    raw = read_regular_file(source)
    validate(raw)
    previous = None
    if target.exists() or target.is_symlink():
        previous = read_regular_file(target)
        validate(previous)
        if previous == raw:
            return "UNCHANGED"
    fd, filename = tempfile.mkstemp(prefix=".tb4h-snapshot-", dir=folder)
    temp = Path(filename)
    try:
        os.fchmod(fd, 0o644)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as dest:
            dest.write(raw)
            dest.flush()
            os.fsync(dest.fileno())
        fd = -1
        # Concurrency guard (not locking): refuse an unexpected new target.
        if previous is None:
            if target.exists() or target.is_symlink():
                raise ValueError("Snapshot appeared during install")
        else:
            if read_regular_file(target) != previous:
                raise ValueError("Snapshot changed during update")
        os.replace(temp, target)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp.exists():
            temp.unlink()
    return "CREATED" if previous is None else "UPDATED"


def main() -> int:
    try:
        if os.geteuid() != 0:
            raise ValueError("Guest root required for controlled snapshot deploy")
        if Path("/etc/hostname").read_text(encoding="utf-8").strip() != "tb4h-controller":
            raise ValueError("Wrong guest hostname")
        outcome = write_snapshot()
    except (OSError, ValueError, KeyError) as exc:
        print(f"TOBE4HOME_PROXMOX_SNAPSHOT_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"TOBE4HOME_PROXMOX_SNAPSHOT_{outcome}=YES")
    print("TOBE4HOME_DISCOVERY=GUEST_COUNTS_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
