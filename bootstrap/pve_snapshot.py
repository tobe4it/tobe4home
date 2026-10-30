#!/usr/bin/env python3
"""Read-only Proxmox inventory snapshot via local pvesh CLI.

Run only on a trusted Proxmox host. No writes and no API credentials stored.
The result is non-secret metadata for tb4h infra_planner.py. It does not
verify external Git, agent, model or CI services.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

IDENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")


def safe_identifier(val, name):
    if not isinstance(val, str) or not IDENT.fullmatch(val):
        raise ValueError(f"Invalid {name}")
    return val


def pvesh(path, *params):
    # All calls are GET, and all arguments are passed as literal argv parts.
    result = subprocess.run(
        ["pvesh", "get", path, "--output-format", "json", *params],
        capture_output=True, text=True, timeout=18, check=True)
    return json.loads(result.stdout)


def export(node, template_storage):
    node = safe_identifier(node, "node")
    template_storage = safe_identifier(template_storage, "template_storage")
    resources = pvesh("/cluster/resources", "--type", "vm")
    nets = pvesh(f"/nodes/{node}/network")
    storages = pvesh(f"/nodes/{node}/storage")
    node_status = pvesh(f"/nodes/{node}/status")
    templates = pvesh(
        f"/nodes/{node}/storage/{template_storage}/content",
        "--content", "vztmpl")
    if not isinstance(resources, list) or not isinstance(nets, list):
        raise ValueError("Unexpected Proxmox resource or network listing")
    if not isinstance(storages, list) or not isinstance(templates, list):
        raise ValueError("Unexpected Proxmox storage or template listing")
    if not isinstance(node_status, dict):
        raise ValueError("Unexpected Proxmox node status")
    memory = node_status.get("memory", {})
    info = node_status.get("cpuinfo", {})
    free_mb = memory.get("free")
    cpus = info.get("cpus")
    if type(free_mb) is not int or free_mb <= 0:
        raise ValueError("Missing numeric Proxmox free RAM")
    if type(cpus) is not int or cpus <= 0:
        raise ValueError("Missing numeric Proxmox physical CPU cores")
    vmids = sorted(set(
        x["vmid"] for x in resources
        if isinstance(x, dict) and type(x.get("vmid")) is int
    ))
    bridges = sorted(set(
        n["iface"] for n in nets
        if isinstance(n, dict) and n.get("type") == "bridge"
        and n.get("active") == 1 and n.get("iface", "").startswith("vmbr")
    ))
    storage_map = {}
    for item in storages:
        if not isinstance(item, dict):
            raise ValueError("Storage listing contains malformed entry")
        identifier = safe_identifier(item.get("storage"), "storage")
        content = item.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Storage content capability must be string")
        bytes_available = item.get("avail")
        if type(bytes_available) is not int:
            raise ValueError(f"Missing available-bytes field for {identifier}")
        storage_map[identifier] = {
            "active": item.get("active") == 1,
            "content": sorted(x.strip() for x in content.split(",") if x.strip()),
            "free_gb": bytes_available // (1024**3),
        }
    return {
        "node": node, "vmids": vmids, "bridges": bridges,
        "templates": sorted(
            item["volid"] for item in templates
            if isinstance(item, dict)
            and isinstance(item.get("volid"), str)
            and item["volid"].startswith(template_storage + ":vztmpl/")
        ),
        "storages": storage_map,
        "free_mb": free_mb // (1024**2),
        "cores_available": cpus,
        "existing_services": {},
        "metadata": {
            "method": "local-pvesh-read-only",
            "note": "Snapshot requires live recheck before any permissioned apply.",
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--template-storage", default="local")
    args = parser.parse_args(argv)
    try:
        result = export(args.node, args.template_storage)
    except (ValueError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print("INVENTORY REFUSED:", str(exc)[:200], file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
