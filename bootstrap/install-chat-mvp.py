#!/usr/bin/env python3
"""Install only the new loopback-only tobe4home Chat MVP in CT1001.

Guest-side root process; stages must come from reviewed bootstrap assets.
Fails closed on pre-existing unrecognized app/service; keeps AnsibleForms intact.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import tempfile

STAGE = Path("/var/lib/tobe4home/chat-stage")
APP = Path("/opt/tobe4home/chat")
ETC = Path("/etc/tobe4home")
SERVICE = Path("/etc/systemd/system/tb4h-chat.service")
ASSETS = ("server.py", "index.html", "app.js", "app.css")
MAX_SIZE = 60_000
SERVICE_TEXT = """[Unit]
Description=tobe4home Chat MVP (SSH tunnel only, read-only)
After=network.target
[Service]
Type=simple
User=tb4h-chat
Group=tb4h-chat
WorkingDirectory=/opt/tobe4home/chat
ExecStart=/usr/bin/python3 -B /opt/tobe4home/chat/server.py
Environment=PYTHONDONTWRITEBYTECODE=1
LoadCredential=llm_api_key:/etc/tobe4home/llm-api-key
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
CapabilityBoundingSet=
AmbientCapabilities=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
[Install]
WantedBy=multi-user.target
"""
DEFAULT_CONFIG = b'{"api_url":"","model":""}\n'


def strict_dir(path: Path, allowed_owners: set[int]) -> None:
    i = path.lstat()
    if (not stat.S_ISDIR(i.st_mode) or stat.S_ISLNK(i.st_mode)
            or i.st_uid not in allowed_owners or i.st_mode & 0o022):
        raise ValueError(f"Unsafe directory: {path}")


def ensure_runtime_directory(path: Path, owner: int = 0) -> None:
    """Repair only our controlled 0700 directories to explicit 0755.

    pct exec may inherit the host bootstrap's umask 077, overriding
    Path.mkdir(mode=0o755). The non-root systemd User/WorkingDirectory
    then fails at CHDIR before server.py can run.
    """
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o755)
    strict_dir(path, {owner})
    info = path.lstat()
    current = stat.S_IMODE(info.st_mode)
    if current not in (0o700, 0o755):
        raise ValueError(f"Unexpected chat directory permissions: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_ino != info.st_ino or opened.st_dev != info.st_dev
                or opened.st_uid != owner):
            raise ValueError("Chat directory changed during permission check")
        os.fchmod(fd, 0o755)
    finally:
        os.close(fd)


def regular(path: Path, owners: set[int], limit: int = MAX_SIZE) -> bytes:
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
            st.st_uid not in owners or st.st_mode & 0o022 or
            st.st_size > limit or st.st_size < 1):
        raise ValueError(f"Unsafe asset: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_ino != st.st_ino:
            raise ValueError("Race while reading asset")
        with os.fdopen(fd, "rb") as reader:
            return reader.read(limit + 1)
    finally:
        pass


def create_exclusive(path: Path, data: bytes, mode: int = 0o644) -> bool:
    if path.exists() or path.is_symlink():
        if regular(path, {0}) != data:
            raise ValueError(f"Refusing locally changed destination: {path}")
        return False
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def checked_json(data: bytes) -> None:
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise ValueError("Invalid Chat config") from exc
    if not isinstance(obj, dict) or set(obj) != {"api_url", "model"}:
        raise ValueError("Invalid Chat config keys")
    if not isinstance(obj["api_url"], str) or not isinstance(obj["model"], str):
        raise ValueError("Invalid Chat config values")
    if len(obj["api_url"]) > 500 or len(obj["model"]) > 128:
        raise ValueError("Chat config too large")


def install(stage: Path = STAGE, app: Path = APP, etc: Path = ETC,
            service: Path = SERVICE) -> dict[str, str]:
    if os.geteuid() != 0:
        raise ValueError("Root in CT1001 required")
    if Path("/etc/hostname").read_text().strip() != "tb4h-controller":
        raise ValueError("Not the tobe4home controller")
    if not Path("/etc/systemd/system/ansibleforms.service").is_file():
        raise ValueError("Existing AnsibleForms missing; not modifying CT1001")
    strict_dir(stage, {0})
    files = {name: regular(stage / name, {0}) for name in ASSETS}
    strict_dir(app.parent, {0}) if app.parent.exists() else None
    if app.exists() or app.is_symlink():
        strict_dir(app, {0})
        for name, blob in files.items():
            if regular(app / name, {0}) != blob:
                raise ValueError("Existing chat asset conflicts: " + name)
    if etc.exists() or etc.is_symlink():
        strict_dir(etc, {0})
        if (etc / "chat.json").exists() or (etc / "chat.json").is_symlink():
            checked_json(regular(etc / "chat.json", {0}, 2048))
        if (etc / "llm-api-key").exists() or (etc / "llm-api-key").is_symlink():
            i = (etc / "llm-api-key").lstat()
            if not stat.S_ISREG(i.st_mode) or i.st_nlink != 1 or i.st_uid != 0 or i.st_size > 2048:
                raise ValueError("Invalid LLM token file")
            if i.st_mode & 0o077:
                raise ValueError("LLM token file must be root-only")
    if service.exists() or service.is_symlink():
        if regular(service, {0}) != SERVICE_TEXT.encode():
            raise ValueError("Existing systemd chat unit conflicts")
    # All existing collisions are checked before writing anything.
    # Explicit fd-based mode repair is essential under umask 077:
    # otherwise systemd User=tb4h-chat cannot traverse WorkingDirectory
    # or load the root-owned, world-readable nonsecret config file.
    # Only these three controlled root-owned directories are changed.
    ensure_runtime_directory(app.parent)
    ensure_runtime_directory(app)
    ensure_runtime_directory(etc)
    result = {}
    for name, blob in files.items():
        result[name] = "CREATED" if create_exclusive(app / name, blob) else "UNCHANGED"
    # Preserve locally configured model settings across reruns.
    if (etc / "chat.json").exists():
        result["chat.json"] = "PRESERVED"
    else:
        create_exclusive(etc / "chat.json", DEFAULT_CONFIG)
        result["chat.json"] = "CREATED"
    if not (etc / "llm-api-key").exists():
        os.close(os.open(etc / "llm-api-key", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
    result["tb4h-chat.service"] = ("CREATED" if create_exclusive(service, SERVICE_TEXT.encode()) else "UNCHANGED")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "tb4h-chat"], check=True)
    # Rerunning the approved installer must recover a failed first start.
    # Restart ONLY the verified, tobe4home-owned unit, not AnsibleForms.
    subprocess.run(["systemctl", "restart", "tb4h-chat"], check=True)
    return result


def main():
    try:
        results = install()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("TOBE4HOME_CHAT_INSTALL_REFUSED: " + str(exc), file=sys.stderr)
        return 2
    for file, state in results.items():
        print(f"TOBE4HOME_CHAT_{state}={file}")
    print("TOBE4HOME_CHAT_MODE=READ_ONLY_PREVIEW")
    print("TOBE4HOME_CHAT_ACCESS=LOOPBACK_SSH_TUNNEL_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
