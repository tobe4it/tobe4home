#!/usr/bin/env python3
"""Install only the two new tobe4home planner assets on verified CT1001.

No Proxmox command, model call, service configuration or deployment.
Fail closed on symlinks, hardlinks, modified files, or unexpected ownership.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile

STAGE = Path("/var/lib/tobe4home")
DATA = Path("/opt/ansibleforms/data")
FILES = {
    "tobe4home-service-plan.yml": "forms",
    "tb4h-service-plan-preview.yml": "playbooks",
}
# The exact initial form published before the AnsibleForms 7.4.2 textarea
# schema compatibility repair. No arbitrary existing file is upgradeable.
APPROVED_PRIOR_GIT_BLOBS = {
    "tobe4home-service-plan.yml": frozenset({
        "214c02698a2ea0650551317c97eee6681df62b4a",
    }),
}


def approved_prior(filename: str, content: bytes) -> bool:
    git_blob = b"blob " + str(len(content)).encode("ascii") + b"\x00" + content
    digest = hashlib.sha1(git_blob, usedforsecurity=False).hexdigest()
    return digest in APPROVED_PRIOR_GIT_BLOBS.get(filename, frozenset())



def checked_dir(path: Path, allowed_owner: set[int]) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("Unsafe directory")
    if info.st_uid not in allowed_owner or info.st_mode & 0o002:
        raise ValueError("Unsafe directory owner or permissions")


def checked_file(path: Path, allowed_owner: set[int]) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid not in allowed_owner or info.st_mode & 0o002
            or not 30 <= info.st_size <= 64_000):
        raise ValueError("Unsafe or unexpected asset: " + path.name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info2 = os.fstat(fd)
        if info2.st_ino != info.st_ino or info2.st_dev != info.st_dev:
            raise ValueError("Asset changed during read")
        with os.fdopen(fd, "rb") as reader:
            fd = -1
            blob = reader.read(64_001)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(blob) != info.st_size:
        raise ValueError("Asset changed or oversized")
    return blob


def install(stage: Path = STAGE, data: Path = DATA, uid: int | None = None,
            gid: int | None = None) -> dict[str, str]:
    if uid is None or gid is None:
        account = pwd.getpwnam("ansibleforms")
        uid, gid = account.pw_uid, account.pw_gid
    if uid == 0 or gid == 0:
        raise ValueError("Refusing privileged AnsibleForms target owner")
    checked_dir(stage, {0, os.geteuid()})
    checked_dir(data, {uid})
    planned: list[tuple[Path, bytes, bytes | None]] = []
    for filename, folder in FILES.items():
        destination = data / folder
        checked_dir(destination, {0, uid})
        target = destination / filename
        incoming = checked_file(stage / filename, {0, os.geteuid()})
        old = None
        if target.exists() or target.is_symlink():
            old = checked_file(target, {uid})
            if old != incoming and not approved_prior(filename, old):
                raise ValueError("Refusing operator-modified asset: " + filename)
        planned.append((target, incoming, old))

    results: dict[str, str] = {}
    for target, incoming, old in planned:
        if old == incoming:
            # A concurrent operator change must never be silently overwritten.
            if checked_file(target, {uid}) != incoming:
                raise ValueError("Concurrent modification: " + target.name)
            results[target.name] = "UNCHANGED"
            continue
        fd, temp_name = tempfile.mkstemp(prefix=".tb4h-plan-", dir=target.parent)
        temp = Path(temp_name)
        try:
            os.fchmod(fd, 0o644)
            os.fchown(fd, uid, gid)
            with os.fdopen(fd, "wb") as writer:
                fd = -1
                writer.write(incoming)
                writer.flush()
                os.fsync(writer.fileno())
            if old is None:
                if target.exists() or target.is_symlink():
                    raise ValueError("Destination appeared while installing: " + target.name)
                # Exclusive creation refuses a newly appearing target.
                os.link(temp, target, follow_symlinks=False)
                results[target.name] = "CREATED"
            else:
                # Only our EXACT previously published Git blob may be replaced.
                # Refuse even the smallest operator edit, and re-check immediately
                # before atomic replacement in the same directory.
                if not approved_prior(target.name, old):
                    raise ValueError("Unapproved predecessor: " + target.name)
                if checked_file(target, {uid}) != old:
                    raise ValueError("Concurrent modification: " + target.name)
                os.replace(temp, target)
                results[target.name] = "UPDATED"
        finally:
            if fd >= 0:
                os.close(fd)
            if temp.exists():
                temp.unlink()
    return results


def main() -> int:
    try:
        if os.geteuid() != 0:
            raise ValueError("Guest root required")
        if Path("/etc/hostname").read_text(encoding="utf-8").strip() != "tb4h-controller":
            raise ValueError("Not the tobe4home controller")
        if not Path("/etc/systemd/system/ansibleforms.service").is_file():
            raise ValueError("Native AnsibleForms missing")
        results = install()
    except (ValueError, OSError, KeyError) as exc:
        print("TOBE4HOME_PLANNER_REFUSED: " + str(exc), file=sys.stderr)
        return 2
    for path, result in results.items():
        print("TOBE4HOME_PLANNER_" + result + "=" + path)
    print("TOBE4HOME_PLANNER_MODE=PREVIEW_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
