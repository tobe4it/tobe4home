#!/usr/bin/env python3
"""Show the initial AnsibleForms login ONLY at the end of a healthy bootstrap.

Execute as guest root via pct exec 1001 from an attended host TTY.
Read only ADMIN_USERNAME and ADMIN_PASSWORD, never the full app.env.
Do not log, persist, send over the network, or put credentials on argv.
The initial password can become obsolete after an operator changes it.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import pwd
import re
import stat
import sys

CONFIG = Path("/opt/ansibleforms/app.env")
EXPECTED_HOSTNAME = "tb4h-controller"


def read_initial_login(path: Path, expected_root_uid: int = 0) -> tuple[str, str]:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("AnsibleForms credentials path is not a regular file")
    if st.st_uid != expected_root_uid or st.st_nlink != 1:
        raise ValueError("AnsibleForms credentials ownership or link count is unexpected")
    if stat.S_IMODE(st.st_mode) & 0o027:
        raise ValueError("AnsibleForms credentials file has unsafe permissions")
    if st.st_size > 32768 or st.st_size < 30:
        raise ValueError("AnsibleForms credentials file has unexpected size")
    # Open with O_NOFOLLOW and compare inode to guard against link/swap races.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if opened.st_ino != st.st_ino or opened.st_dev != st.st_dev:
            raise ValueError("AnsibleForms credentials file changed during read")
        if opened.st_nlink != 1 or opened.st_uid != expected_root_uid:
            raise ValueError("Untrusted credentials file after opening")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            data = stream.read(32769)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > 32768:
        raise ValueError("Oversized AnsibleForms credentials file")
    values: dict[str, str] = {}
    for line in data.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, sep, value = line.partition("=")
        if sep and name in ("ADMIN_USERNAME", "ADMIN_PASSWORD"):
            if name in values:
                raise ValueError("Duplicate initial login field")
            values[name] = value
    username = values.get("ADMIN_USERNAME", "")
    password = values.get("ADMIN_PASSWORD", "")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", username):
        raise ValueError("AnsibleForms initial username is missing or invalid")
    if not re.fullmatch(r"[A-Za-z0-9_@!%+.,:=-]{12,256}", password):
        raise ValueError("Initial password missing or unexpected format")
    return username, password


def render_login(ip: str, username: str, password: str) -> str:
    addr = ipaddress.IPv4Address(ip)
    if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified:
        raise ValueError("No usable IPv4 address for the new controller")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", username):
        raise ValueError("Invalid login username")
    if not re.fullmatch(r"[A-Za-z0-9_@!%+.,:=-]{12,256}", password):
        raise ValueError("Invalid initial login password")
    return (
        "\n"
        "========================================================\n"
        "  TOBE4HOME – CONTROLLER BEREIT, JETZT ANMELDEN\n"
        "========================================================\n"
        "  CT:       1001 · tb4h-controller\n"
        f"  Adresse:  https://{addr}/\n"\n        f"  Einrichtung: https://{addr}/form/tobe4home-start\\n"
        f"  Benutzer: {username}\n"
        f"  Passwort: {password}\n"
        "--------------------------------------------------------\n"
        "  Nach der Anmeldung: Einrichtung öffnen und Ziele wählen.\\n"\n        "  Das Zertifikat ist zunächst selbstsigniert.\n"
        "  Diese Zugangsdaten nicht in Chats, Tickets oder Logs kopieren.\n"
        "  Passwort nach der ersten erfolgreichen Anmeldung ändern.\n"
        "  Falls schon geändert: Hier steht nur das ursprüngliche Passwort.\n"
        "========================================================\n"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True, help="Guest IPv4, not a password")
    args = parser.parse_args(argv)
    try:
        if os.geteuid() != 0:
            raise ValueError("Credential display requires root inside CT1001")
        if Path("/etc/hostname").read_text(encoding="utf-8").strip() != EXPECTED_HOSTNAME:
            raise ValueError("Wrong controller hostname")
        if pwd.getpwnam("ansibleforms").pw_uid == 0:
            raise ValueError("AnsibleForms system user is privileged")
        username, password = read_initial_login(CONFIG)
        # Do not print partial login information before all validation passes.
        panel = render_login(args.ip, username, password)
    except (ValueError, OSError, KeyError, UnicodeError) as exc:
        # The exception text is never derived from credential values.
        print(f"FIRST_LOGIN_DISPLAY_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(panel, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
