#!/usr/bin/env python3
"""Repair native AnsibleForms 7.4.2 *code* permissions after restrictive umask.

Only root-owned release/runtime files get group=ansibleforms and g+rX.
The separate app.env and rte.env are checked and get group-read permission
without becoming world-readable. Persistent data, home, secrets, database,
SSH keys, private certificates and installer backups are never traversed.
Idempotent. Does NOT reinstall or restart services.
"""
from __future__ import annotations

import argparse
import grp
import os
from pathlib import Path
import pwd
import stat
import sys

VERSION = "7.4.2"
BASE = Path("/opt/ansibleforms")


def kind(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"Unexpected symbolic link: {path}")
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError(f"Unexpected special file: {path}")
    return info


def guarded_tree(root: Path, uid: int) -> list[tuple[Path, os.stat_result]]:
    """Do not follow symlinks. Refuse any code file not owned by root."""
    files = []
    root_info = kind(root)
    if not stat.S_ISDIR(root_info.st_mode):
        raise ValueError(f"Not a directory: {root}")
    for parent, names, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(parent)
        for path in [current] + [current / name for name in names + filenames]:
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode):
                # Upstream deliberately links "node" to runtime and
                # "persistent"/"custom.js" into private data. Never follow.
                if path == current:
                    raise ValueError("Symlinked parent")
                continue
            if not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise ValueError(f"Unexpected code file type: {path}")
            if st.st_uid != uid:
                raise ValueError(f"Unexpected code owner: {path}")
            if path != current or path == root:
                files.append((path, st))
    # The walk includes a subdir once via names and once as current: dedup.
    unique = {}
    for path, st in files:
        unique[path] = st
    return sorted(unique.items(), key=lambda x: str(x[0]))


def mode_for_code(st: os.stat_result) -> int:
    mode = stat.S_IMODE(st.st_mode)
    if stat.S_ISDIR(st.st_mode):
        if not (mode & stat.S_IRUSR and mode & stat.S_IXUSR):
            raise ValueError("Code directory lacks owner read/traverse rights")
        return mode | stat.S_IRGRP | stat.S_IXGRP
    # Preserve which files are executable; do not execute non-executable data.
    if not (mode & stat.S_IRUSR):
        raise ValueError("Code file lacks owner read permission")
    return mode | stat.S_IRGRP | (stat.S_IXGRP if mode & stat.S_IXUSR else 0)


def plan(base: Path, user: str, expected_uid: int = 0,
         gid: int | None = None) -> list[tuple[Path, int, int]]:
    """Return path + target group + target mode, without changing files."""
    if gid is None:
        gid = grp.getgrnam(user).gr_gid
    if not base.is_absolute() or base.is_symlink():
        raise ValueError("Installation root must be a real absolute directory")
    base_st = kind(base)
    if base_st.st_uid != expected_uid or not stat.S_ISDIR(base_st.st_mode):
        raise ValueError("Untrusted installation root")
    current = base / "current"
    if not current.is_symlink() or os.readlink(current) != f"releases/{VERSION}":
        raise ValueError("Unexpected active AnsibleForms release")
    code = [base, base / "releases", base / "runtime"]
    for root in code:
        info = kind(root)
        if info.st_uid != expected_uid or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"Untrusted code directory: {root}")
    release = base / "releases" / VERSION
    if release.is_symlink():
        raise ValueError("Release directory cannot be a symlink")
    changes = []
    # Base itself is a shared directory: allow listing/traversing via group.
    for path in [base] + [base / "releases", base / "runtime"]:
        st = kind(path)
        target = mode_for_code(st)
        if st.st_gid != gid or stat.S_IMODE(st.st_mode) != target:
            changes.append((path, gid, target))
    # Runtime is shared (Node.js, uv, Python); release holds only trusted code.
    # Do NOT traverse base/data, home, installer-backups, or env files.
    for root in [release, base / "runtime"]:
        for path, st in guarded_tree(root, expected_uid):
            target = mode_for_code(st)
            if st.st_gid != gid or stat.S_IMODE(st.st_mode) != target:
                changes.append((path, gid, target))
    # Upstream writeEnv writes 0640 but old umask 077 made 0600.
    # Verify the exact expected root:ansibleforms ownership first.
    for suffix in ("app", "rte"):
        env = base / f"{suffix}.env"
        st = kind(env)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != expected_uid or st.st_gid != gid:
            raise ValueError(f"Unexpected ownership of {env.name}")
        m = stat.S_IMODE(st.st_mode)
        if m & 0o007 or m & stat.S_IWGRP or m & stat.S_IXGRP:
            raise ValueError(f"Unexpected permissive {env.name} mode")
        target = m | stat.S_IRGRP
        if m != target:
            changes.append((env, gid, target))
    # Every target now validated; only selected paths are modified.
    return sorted(set(changes), key=lambda item: str(item[0]))


def execute(changes: list[tuple[Path, int, int]]) -> int:
    updated = 0
    for path, gid, mode in changes:
        st = kind(path)
        if st.st_uid != 0:
            raise ValueError("Code changed ownership during repair")
        # Do not follow symbolic links even in the presence of prior validation.
        os.chown(path, -1, gid, follow_symlinks=False)
        os.chmod(path, mode, follow_symlinks=False)
        updated += 1
    return updated


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        print("REFUSED: root inside CT1001 is required", file=sys.stderr)
        return 2
    try:
        # Defense in depth: never execute this on the host or another guest.
        actual_hostname = Path("/etc/hostname").read_text().strip()
        if actual_hostname != "tb4h-controller":
            raise ValueError("Not the expected tb4h-controller guest")
        if pwd.getpwnam("ansibleforms").pw_uid == 0:
            raise ValueError("AnsibleForms cannot run as root")
        fixes = plan(BASE, "ansibleforms")
        print(f"ANSIBLEFORMS_PROGRAM_PERMISSION_FIXES={len(fixes)}")
        if args.apply:
            n = execute(fixes)
            if plan(BASE, "ansibleforms"):
                raise ValueError("Permission repair not idempotent")
            print(f"ANSIBLEFORMS_PROGRAM_REPAIR_APPLIED={n}")
        else:
            print("READ_ONLY_CHECK_NO_CHANGES")
        print("PRIVATE_DATA_ENV_BACKUPS_AND_CERTIFICATES_NOT_TRAVERSED")
        return 0
    except (OSError, KeyError, ValueError, NotImplementedError) as exc:
        print(f"ANSIBLEFORMS_PERMISSION_REPAIR_REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
