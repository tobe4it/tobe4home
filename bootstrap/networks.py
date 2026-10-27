#!/usr/bin/env python3
"""Read-only Proxmox bridge discovery and interactive pre-LXC network selection.

Neither host bridge names nor observed VLAN IDs imply a security purpose.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

BRIDGE_RE = re.compile(r"^vmbr[0-9]+$")
VALID_VLAN_MIN = 1
VALID_VLAN_MAX = 4094


def read_json(command: list[str], *, required: bool = True):
    try:
        proc = subprocess.run(command, check=True, capture_output=True, text=True)
        return json.loads(proc.stdout or "[]")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        if required:
            raise RuntimeError(f"Read-only network discovery failed: {command[0]}") from exc
        return []


def analyze_bridges(links: list[dict], addresses: list[dict], routes: list[dict]) -> list[dict]:
    addr_by_name = {
        row.get("ifname"): [
            f"{x['local']}/{x['prefixlen']}"
            for x in row.get("addr_info", [])
            if x.get("family") == "inet" and "local" in x and "prefixlen" in x
        ]
        for row in addresses
    }
    default_devs = {r.get("dev") for r in routes if r.get("dst") == "default"}
    candidates = []
    for link in links:
        name = link.get("ifname", "")
        kind = link.get("linkinfo", {}).get("info_kind")
        if not BRIDGE_RE.fullmatch(name) or kind != "bridge":
            continue
        data = link.get("linkinfo", {}).get("info_data", {})
        candidates.append({
            "name": name,
            "up": link.get("operstate") == "UP" or "UP" in link.get("flags", []),
            "vlan_aware": data.get("vlan_filtering") in (1, True, "1"),
            "host_ipv4": addr_by_name.get(name, []),
            "host_default_route": name in default_devs,
        })
    return sorted(candidates, key=lambda c: int(c["name"][4:]))


def discover() -> list[dict]:
    links = read_json(["ip", "-j", "-d", "link", "show", "type", "bridge"])
    addresses = read_json(["ip", "-j", "-4", "addr", "show"], required=False)
    routes = read_json(["ip", "-j", "-4", "route", "show", "default"], required=False)
    result = analyze_bridges(links, addresses, routes)
    if not result:
        raise RuntimeError("No Proxmox vmbrN bridges were discovered")
    return result


def check_selection(candidates: list[dict], name: str, vlan_tag: int | None) -> dict:
    match = next((c for c in candidates if c["name"] == name), None)
    if match is None:
        raise ValueError("Selected bridge is not a discovered Proxmox vmbrN bridge")
    if vlan_tag is not None:
        if not VALID_VLAN_MIN <= vlan_tag <= VALID_VLAN_MAX:
            raise ValueError("VLAN tag must be between 1 and 4094")
        if not match["vlan_aware"]:
            raise ValueError("Tagged VLAN requires a VLAN-aware bridge")
    if not match["up"]:
        raise ValueError("Selected bridge is down")
    return match


def display(candidates: list[dict], file=sys.stderr) -> None:
    print("Read-only Proxmox bridge discovery:", file=file)
    for idx, c in enumerate(candidates, 1):
        status = "UP" if c["up"] else "DOWN"
        aware = "yes" if c["vlan_aware"] else "no"
        route = "host default route: YES" if c["host_default_route"] else "host default route: no"
        print(f" {idx}. {c['name']} | {status} | VLAN-aware: {aware} | {route}", file=file)
        if c["host_ipv4"]:
            print("    Host address present (not proof of guest DHCP or SSH reachability)", file=file)
    print("No network is automatically recommended: purpose and security must be confirmed.", file=file)
    print("Prefer a restricted infrastructure/management segment with verified DHCP,", file=file)
    print("package mirror reachability and SSH administration; avoid exposing Proxmox.", file=file)
    print("A vmbr number is NOT a VLAN ID. VLAN tags are explicit 1–4094.", file=file)


def pick(candidates: list[dict]) -> tuple[str, int | None]:
    if not sys.stdin.isatty():
        raise ValueError("Interactive selection requires a terminal; otherwise use --bridge")
    display(candidates)
    while True:
        print("Select network number (blank cancels): ", end="", file=sys.stderr, flush=True)
        choice = input().strip()
        if not choice:
            raise ValueError("Network selection cancelled")
        if choice.isascii() and choice.isdigit() and 1 <= int(choice) <= len(candidates):
            chosen = candidates[int(choice) - 1]
            break
        print("Invalid selection.", file=sys.stderr)
    if chosen["vlan_aware"]:
        print("VLAN tag 1–4094, or blank for untagged: ", end="", file=sys.stderr, flush=True)
        raw = input().strip()
        if raw and (not raw.isascii() or not raw.isdigit()):
            raise ValueError("Invalid VLAN tag")
        tag = int(raw) if raw else None
    else:
        tag = None
        print("Bridge is not VLAN-aware: selecting untagged network.", file=sys.stderr)
    check_selection(candidates, chosen["name"], tag)
    return chosen["name"], tag


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--select", action="store_true")
    mode.add_argument("--validate", metavar="BRIDGE")
    parser.add_argument("--tag", type=int)
    args = parser.parse_args()
    try:
        bridges = discover()
        if args.list:
            display(bridges, file=sys.stdout)
        elif args.select:
            name, tag = pick(bridges)
            print(f"{name} {tag if tag is not None else '-'}")
        else:
            found = check_selection(bridges, args.validate, args.tag)
            print(f"Bridge {found['name']}: UP; VLAN tag: {args.tag or 'untagged'}")
    except (RuntimeError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
