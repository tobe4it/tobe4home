#!/usr/bin/env python3
"""Fail-closed ownership check for an EXISTING tobe4home controller CT1001.

Proxmox may normalize/sort the tags field. Verify membership as complete
semicolon-delimited tokens, not the order they were supplied to pct create.
Reads only the already-scoped pct config 1001 data on stdin; never writes.
"""
from __future__ import annotations

import re
import sys

REQUIRED_TAGS = frozenset(("tobe4home", "controller"))
SINGLE_VALUE_FIELDS = frozenset(("hostname", "unprivileged", "tags", "rootfs"))


def check_config(text: str) -> None:
    if not isinstance(text, str) or not text.strip() or len(text) > 65536:
        raise ValueError("Missing or oversized Proxmox CT1001 config")
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(": ")
        if separator and key in SINGLE_VALUE_FIELDS:
            if key in values:
                raise ValueError(f"Duplicate Proxmox config field: {key}")
            values[key] = value.strip()
    if values.get("hostname") != "tb4h-controller":
        raise ValueError("CT1001 does not have the tobe4home controller hostname")
    if values.get("unprivileged") != "1":
        raise ValueError("CT1001 is not an unprivileged LXC")
    raw = values.get("tags", "")
    tags = raw.split(";")
    if (not tags or any(not re.fullmatch(r"[a-z0-9_-]{1,64}", tag) for tag in tags)
            or len(tags) != len(set(tags))):
        raise ValueError("Invalid or ambiguous Proxmox tags")
    if not REQUIRED_TAGS.issubset(set(tags)):
        raise ValueError("CT1001 is missing tobe4home controller tags")
    rootfs = values.get("rootfs", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+:(?:subvol-1001-disk-[0-9]+|[A-Za-z0-9_.-]+),size=[0-9]+[GMK](?:,.*)?", rootfs):
        raise ValueError("CT1001 rootfs entry is absent or unexpected")


def main() -> int:
    try:
        check_config(sys.stdin.read())
    except ValueError as exc:
        print(f"CONTROLLER_IDENTITY_REFUSED: {exc}", file=sys.stderr)
        return 2
    print("CONTROLLER_IDENTITY_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
