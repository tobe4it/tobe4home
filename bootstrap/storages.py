#!/usr/bin/env python3
"""Read-only discovery of Proxmox LXC rootfs-capable storages.

Proxmox VE supports: pvesm status --content rootdir
Do not infer rootdir capability from raw unfiltered pvesm status or an
undocumented pvesm config subcommand.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess

STORAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_rootdir_status(output: str) -> list[dict[str, str]]:
    lines = [line.split() for line in output.splitlines() if line.strip()]
    if not lines or lines[0][:3] != ["Name", "Type", "Status"]:
        raise ValueError("Unexpected pvesm rootdir status table header")
    result = []
    seen = set()
    for columns in lines[1:]:
        if len(columns) < 3:
            raise ValueError("Unexpected pvesm rootdir status row")
        name, storage_type, status = columns[:3]
        if not STORAGE_RE.fullmatch(name) or name in seen:
            raise ValueError("Invalid/duplicate storage name")
        seen.add(name)
        if status == "active":
            result.append({"name": name, "type": storage_type, "status": status})
    return result


def discover() -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            ["pvesm", "status", "--content", "rootdir"],
            capture_output=True, check=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Failed to query Proxmox rootdir-capable storage") from exc
    storages = parse_rootdir_status(completed.stdout)
    if not storages:
        raise RuntimeError("No active Proxmox storage supports LXC rootdir")
    return storages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", required=True)
    args = parser.parse_args()
    try:
        storages = discover()
    except (ValueError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    if args.json:
        print(json.dumps(storages, sort_keys=True))


if __name__ == "__main__":
    main()
