#!/usr/bin/env python3
"""Install the tobe4home welcome form in the EXISTING native AnsibleForms CT.

- Only the two tobe4home-owned filenames.
- Does not delete/edit upstream demo forms or the admin config/seed.
- Never replaces an unexpected different file.
- Safe to re-run on --resume; no Proxmox or network access.
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
ASSETS = {
    "tobe4home-start.yml": ("tobe4home-start.yml", "forms"),
    "tb4h-onboarding-preview.yml": ("tb4h-onboarding-preview.yml", "playbooks"),
}
HOSTNAME = "tb4h-controller"

# Exact Git blob digests of the previous shipped tobe4home welcome assets.
# Updates those exact revisions only; never replaces operator-modified files.
PREVIOUS_GIT_BLOBS = {
    "tobe4home-start.yml": frozenset({
        "936a01a4ceaa113633e12be3f8f50ebc7037210e",
        "542d547c291fcf10be655055673a5a5dc02d7307",
    }),
    "tb4h-onboarding-preview.yml": frozenset({
        "9f73491b8239a483e2d4390d5498499151e14be4",
        "d2ae51227413f18b7ba10e6e2b080703793183ac",
    }),
}


def approved_previous_blob(name: str, data: bytes) -> bool:
    head = b"blob " + str(len(data)).encode("ascii") + b"\x00"
    digest = hashlib.sha1(head + data, usedforsecurity=False).hexdigest()
    return digest in PREVIOUS_GIT_BLOBS.get(name, frozenset())



def real_dir(path: Path) -> None:
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Unexpected non-directory or symlink: {path}")


def checked_data(data: Path, owner_uid: int) -> None:
    real_dir(data)
    st = data.lstat()
    if st.st_uid != owner_uid:
        raise ValueError("AnsibleForms data directory has unexpected owner")
    if stat.S_IMODE(st.st_mode) & 0o002:
        raise ValueError("AnsibleForms data directory is world writable")


def stage_bytes(path: Path) -> bytes:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > 128_000 or st.st_size < 30:
        raise ValueError(f"Unexpected staged asset: {path.name}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        with os.fdopen(fd, "rb") as reader:
            fd = -1
            blob = reader.read(128_001)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(blob) > 128_000:
        raise ValueError("Staged asset too large")
    return blob


def install_asset(source: Path, target: Path, uid: int, gid: int) -> str:
    expected = stage_bytes(source)
    if target.exists() or target.is_symlink():
        st = target.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError(f"Unexpected target file type: {target.name}")
        current = stage_bytes(target)
        if current == expected:
            return "UNCHANGED"
        if not approved_previous_blob(target.name, current):
            raise ValueError(f"Existing locally modified form/playbook; refusing replacement: {target.name}")
        upgrading = True
    else:
        upgrading = False
    fd, temp_name = tempfile.mkstemp(prefix=".tb4h-", dir=target.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o644)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "wb") as writer:
            writer.write(expected)
            writer.flush()
            os.fsync(writer.fileno())
        fd = -1
        if upgrading:
            # Check the previous published bytes again directly before the
            # atomic replacement; never replace a subsequent operator edit.
            st = target.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise ValueError("Destination changed during upgrade")
            if not approved_previous_blob(target.name, stage_bytes(target)):
                raise ValueError("Destination was modified during upgrade")
        elif target.exists() or target.is_symlink():
            raise ValueError("Destination appeared during asset deployment")
        os.replace(temp, target)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp.exists():
            temp.unlink()
    return "UPDATED" if upgrading else "CREATED"


def deploy(stage: Path = STAGE, data: Path = DATA, owner_uid: int | None = None, owner_gid: int | None = None) -> dict:
    if owner_uid is None or owner_gid is None:
        account = pwd.getpwnam("ansibleforms")
        owner_uid, owner_gid = account.pw_uid, account.pw_gid
    if owner_uid == 0 or owner_gid == 0:
        raise ValueError("AnsibleForms owner must not be root")
    real_dir(stage)
    checked_data(data, owner_uid)
    for parent in ("forms", "playbooks"):
        folder = data / parent
        if folder.exists() or folder.is_symlink():
            real_dir(folder)
        else:
            folder.mkdir(mode=0o755)
            os.chown(folder, owner_uid, owner_gid)
        # Only trust the AnsibleForms user or root to own a direct asset folder.
        if folder.lstat().st_uid not in (0, owner_uid):
            raise ValueError(f"Unexpected destination directory owner: {parent}")
    # Check every existing target before writing ANY asset, so a partial
    # deployment cannot occur if the operator modified one of the files.
    for name, (dst, folder) in ASSETS.items():
        source_bytes = stage_bytes(stage / name)
        target = data / folder / dst
        if target.exists() or target.is_symlink():
            existing = target.lstat()
            if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                raise ValueError(f"Unexpected target file type: {dst}")
            current_bytes = stage_bytes(target)
            if current_bytes != source_bytes and not approved_previous_blob(dst, current_bytes):
                raise ValueError(f"Existing locally modified form/playbook; refusing replacement: {dst}")
    results = {}
    for name, (dst, folder) in ASSETS.items():
        results[name] = install_asset(stage / name, data / folder / dst, owner_uid, owner_gid)
    return results


def main() -> int:
    try:
        if os.geteuid() != 0:
            raise ValueError("Guest root is required")
        if Path("/etc/hostname").read_text(encoding="utf-8").strip() != HOSTNAME:
            raise ValueError("Wrong controller")
        if not Path("/etc/systemd/system/ansibleforms.service").is_file():
            raise ValueError("AnsibleForms not installed")
        results = deploy()
    except (ValueError, OSError, KeyError) as exc:
        print(f"TOBE4HOME_ONBOARDING_REFUSED: {exc}", file=sys.stderr)
        return 2
    for name, outcome in results.items():
        print(f"TOBE4HOME_ONBOARDING_{outcome}: {name}")
    print("TOBE4HOME_ONBOARDING_PATH=/form/tobe4home-start")
    print("TOBE4HOME_ONBOARDING_MODE=PREVIEW_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
