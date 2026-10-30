#!/usr/bin/env python3
"""Read-only, privacy-minimized Proxmox guest inventory for tobe4home.

Runs only on the Proxmox host, never inside CT1001. Does not inspect running
services inside guests and never includes names, IPs, VMIDs or credentials.
This is a point-in-time snapshot, not live discovery.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys

MAX_GUESTS = 2000
VMID = re.compile(r"^[1-9][0-9]{1,8}$")
STATUSES = frozenset({"running", "stopped", "paused", "suspended"})


def parse_list(raw: str, kind: str) -> dict:
    if kind not in {"lxc", "qemu"}:
        raise ValueError("Unsupported Proxmox inventory kind")
    rows = raw.splitlines()
    if not rows or len(rows) > MAX_GUESTS + 1:
        raise ValueError("Missing or excessive Proxmox list output")
    header = rows[0].split()
    if not header or header[0] != "VMID":
        raise ValueError("Unexpected Proxmox list header")
    status_pos = 1 if kind == "lxc" else 2
    if len(header) <= status_pos or header[status_pos] != "Status":
        # qm list header is VMID NAME STATUS; avoid position-based case issues.
        if kind != "qemu" or [x.upper() for x in header[:3]] != ["VMID", "NAME", "STATUS"]:
            raise ValueError("Unexpected Proxmox status column")
    found: set[int] = set()
    count = running = 0
    for row in rows[1:]:
        if not row.strip():
            continue
        columns = row.split()
        if len(columns) <= status_pos or not VMID.fullmatch(columns[0]):
            raise ValueError("Invalid VMID or missing status in inventory")
        ident = int(columns[0])
        if ident in found:
            raise ValueError("Duplicate Proxmox VMID")
        found.add(ident)
        status = columns[status_pos].lower()
        if status not in STATUSES:
            raise ValueError("Unrecognized Proxmox guest status")
        if ident == 1001:  # the controller itself is not an existing service
            continue
        count += 1
        if status == "running":
            running += 1
    return {"total": count, "running": running}


def run_list(command: tuple[str, ...]) -> str:
    env = os.environ.copy()
    env.update({"LC_ALL": "C", "LANG": "C"})
    p = subprocess.run(command, env=env, capture_output=True,
                       text=True, timeout=15, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"Read-only {command[0]} inventory query failed")
    if len(p.stdout) > 250_000:
        raise ValueError("Excessive Proxmox inventory output")
    if not p.stdout.strip():
        # Proxmox `qm list` can return an empty stdout with exit 0 when
        # the node has no QEMU guests. This is normal for LXC-only hosts.
        # Accept it ONLY after the command has succeeded without stderr;
        # preserve strict header validation for any nonempty output.
        if command == ("qm", "list") and not p.stderr.strip():
            return "VMID NAME STATUS\n"
        raise ValueError(f"Empty output from {command[0]} inventory query")
    return p.stdout


def overview(lxc_output: str, qemu_output: str, at: datetime | None = None) -> dict:
    lxc = parse_list(lxc_output, "lxc")
    qemu = parse_list(qemu_output, "qemu")
    instant = at or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("UTC timestamp required")
    return {
        "schema": 1,
        "source": "proxmox-host-readonly",
        "collected_at_utc": instant.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "lxc": lxc,
        "qemu": qemu,
        "note": "Nur Proxmox-Gäste, keine Erkennung von Anwendungen in den Gästen",
    }


def main() -> int:
    try:
        # Only the host root can run the trusted Proxmox inventory commands.
        if os.geteuid() != 0:
            raise ValueError("Proxmox host root required")
        result = overview(run_list(("pct", "list")), run_list(("qm", "list")))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"TOBE4HOME_INVENTORY_REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
