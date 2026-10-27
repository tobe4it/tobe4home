#!/usr/bin/env python3
"""tobe4home: bounded, deterministic infrastructure planning.

READ ONLY: This module never connects to Proxmox, calls OpenTofu/Ansible,
creates LXC guests, or stores credentials.  Inventories are explicitly
provided snapshots.  The provider and any execution approval are separate.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
PVE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")
BRIDGE_RE = re.compile(r"^vmbr[0-9]{1,3}$")
TEMPLATE_RE = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}:vztmpl/"
    r"(rockylinux|almalinux)-(9|10)-[a-zA-Z0-9._-]+\.tar\.(xz|gz|zst)$"
)
ROLE_DEFAULTS = {
    "git": {"cores": 2, "memory_mb": 2048, "disk_gb": 20,
            "why": "Git history, Forgejo and reviewed Ansible changes"},
    "agent": {"cores": 2, "memory_mb": 4096, "disk_gb": 32,
              "why": "Sandbox for editing prompt-generated Ansible branches"},
    "model": {"cores": 4, "memory_mb": 8192, "disk_gb": 64,
              "why": "Optional local CPU model endpoint; model suitability must be verified"},
    "ci": {"cores": 2, "memory_mb": 2048, "disk_gb": 20,
           "why": "Isolated job execution and validation"},
}
ALLOWED_MODES = {"new", "existing", "omit"}
DEFAULT_VMID_FROM = 1002
DEFAULT_VMID_TO = 1099


def require_object(obj, name):
    if not isinstance(obj, dict):
        raise ValueError(f"{name} must be an object")
    return obj


def positive_integer(value, name, minimum=0, maximum=1_000_000):
    if type(value) is not int or not (minimum <= value <= maximum):
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def check_id(value, name, regex=PVE_ID_RE):
    if not isinstance(value, str) or not regex.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def normalize(site, choices, inventory):
    site = require_object(site, "site")
    choices = require_object(choices, "choices")
    inventory = require_object(inventory, "inventory")
    for forbidden in ("password", "token", "secret", "private_key", "api_token"):
        def has_secret(obj):
            return any(
                forbidden in str(key).lower()
                for key in obj
            )
        if has_secret(site) or has_secret(choices) or has_secret(inventory):
            raise ValueError("Inputs must not contain credentials or secret keys")
    clean_site = {
        "prefix": check_id(site.get("prefix", "tb4h"), "prefix", ID_RE),
        "node": check_id(site.get("node"), "node"),
        "storage": check_id(site.get("storage"), "storage"),
        "bridge": check_id(site.get("bridge"), "bridge", BRIDGE_RE),
        "template": check_id(site.get("template"), "template", TEMPLATE_RE),
        "dns_resolver": str(ipaddress.IPv4Address(site.get("dns_resolver", ""))),
        "vmid_from": positive_integer(site.get("vmid_from", DEFAULT_VMID_FROM),
                                      "vmid_from", 100, 999999999),
        "vmid_to": positive_integer(site.get("vmid_to", DEFAULT_VMID_TO),
                                    "vmid_to", 100, 999999999),
    }
    if clean_site["vmid_to"] < clean_site["vmid_from"]:
        raise ValueError("Invalid VMID range")
    if (clean_site["vmid_to"] - clean_site["vmid_from"]) > 1000:
        raise ValueError("VMID planning range is too broad")
    if any(ipaddress.IPv4Address(clean_site["dns_resolver"]).is_link_local
           for _ in (0,)):
        raise ValueError("Link-local DNS is not supported")
    if inventory.get("node") != clean_site["node"]:
        raise ValueError("Snapshot does not belong to selected Proxmox node")
    if clean_site["bridge"] not in inventory.get("bridges", []):
        raise ValueError("Selected bridge not verified by inventory")
    if clean_site["template"] not in inventory.get("templates", []):
        raise ValueError("Selected template not verified in inventory")
    if clean_site["storage"] not in inventory.get("storages", {}):
        raise ValueError("Selected rootfs storage not verified")
    for key in ("bridges", "templates", "vmids"):
        if not isinstance(inventory.get(key), list):
            raise ValueError(f"Snapshot field {key} must be a list")
    vmids = inventory["vmids"]
    if any(type(i) is not int or i < 100 for i in vmids) or len(vmids) != len(set(vmids)):
        raise ValueError("Invalid VMID inventory")
    storage = inventory["storages"][clean_site["storage"]]
    require_object(storage, "storage")
    if storage.get("active") is not True or "rootdir" not in storage.get("content", []):
        raise ValueError("Storage is not active or cannot hold LXC rootdirs")
    for key in ("free_mb", "cores_available"):
        positive_integer(inventory.get(key), key, 0)
    positive_integer(storage.get("free_gb"), "free_gb", 0)
    existing = require_object(inventory.get("existing_services", {}), "existing_services")
    clean_choices = {}
    for role in ROLE_DEFAULTS:
        mode = choices.get(role)
        if mode not in ALLOWED_MODES:
            raise ValueError(f"Select new/existing/omit for {role}")
        # A git repository and a coding-agent plus model endpoint are required
        # for the promised prompt-to-Ansible workflow. Without them, reject
        # instead of silently describing an incomplete controller as ready.
        if role in ("git", "agent", "model") and mode == "omit":
            raise ValueError(f"{role} is mandatory for prompt-to-Ansible mode")
        if mode == "existing":
            entry = require_object(existing.get(role), f"existing_services.{role}")
            if entry.get("verified") is not True or not isinstance(entry.get("endpoint"), str):
                raise ValueError(f"Existing {role} service must be verified")
            endpoint = entry["endpoint"]
            if not endpoint.startswith("https://") or len(endpoint) > 512:
                raise ValueError(f"Existing {role} endpoint must use HTTPS")
        clean_choices[role] = mode
    return clean_site, clean_choices, inventory


def compile_plan(site, choices, inventory):
    site, choices, inventory = normalize(site, choices, inventory)
    used = set(inventory["vmids"]) | {1000, 1001}
    available = (
        i for i in range(site["vmid_from"], site["vmid_to"] + 1)
        if i not in used
    )
    guests = []
    for role, preset in ROLE_DEFAULTS.items():
        if choices[role] != "new":
            continue
        try:
            vmid = next(available)
        except StopIteration as exc:
            raise ValueError(f"VMID range exhausted before allocating {role}") from exc
        guests.append({
            "role": role, "vmid": vmid, "hostname": f"{site['prefix']}-{role}",
            "cores": preset["cores"], "memory_mb": preset["memory_mb"],
            "disk_gb": preset["disk_gb"], "rationale": preset["why"],
            "node": site["node"], "bridge": site["bridge"],
            "storage": site["storage"], "template": site["template"],
            "dns_resolver": site["dns_resolver"], "unprivileged": True,
            "started": False, "firewall": True,
        })
    total_ram = sum(g["memory_mb"] for g in guests)
    total_disk = sum(g["disk_gb"] for g in guests)
    remaining_ram = inventory["free_mb"] - total_ram
    remaining_disk = inventory["storages"][site["storage"]]["free_gb"] - total_disk
    # Leave explicit overhead: when capacity values are estimates, reject.
    if remaining_ram < 512:
        raise ValueError("Insufficient verified memory; reserve at least 512 MiB")
    if remaining_disk < 8:
        raise ValueError("Insufficient rootfs storage; reserve at least 8 GiB")
    total_cores = sum(g["cores"] for g in guests)
    if total_cores > inventory["cores_available"] * 2:
        raise ValueError("Controller planning CPU overcommit exceeds limit 2x")
    payload = {
        "schema": 1, "mode": "preview_only", "approved": False,
        "site": site, "choices": choices,
        "inventory": {
            "node": inventory["node"],
            "existing_vmids": sorted(inventory["vmids"]),
            "available_memory_mb": inventory["free_mb"],
            "available_cores": inventory["cores_available"],
            "storage_free_gb": inventory["storages"][site["storage"]]["free_gb"],
        },
        "totals": {
            "new_guests": len(guests), "ram_mb": total_ram,
            "disk_gb": total_disk, "cores": total_cores,
        },
        "guests": guests,
        "existing_services": {
            r: inventory["existing_services"][r]["endpoint"]
            for r in ROLE_DEFAULTS if choices[r] == "existing"
        },
        "warnings": [
            "Inventory is a point-in-time snapshot; recheck prior to any apply.",
            "OpenTofu state must be private, durable and backed up before deployment.",
            "No API credentials, Proxmox changes or guest package installations are generated.",
            "Existing VMIDs must never be imported or modified without separate approval.",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload["plan_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def render_opentofu(plan):
    """Render prospective resources only. No terraform backend or apply action."""
    if plan.get("mode") != "preview_only" or plan.get("approved") is not False:
        raise ValueError("Only read-only plans can be rendered")
    guests = plan["guests"]
    out = [
        "# GENERATED PREVIEW: NOT AN APPROVED DEPLOYMENT",
        f"# plan_sha256: {plan['plan_sha256']}",
        "# Inspect OpenTofu state, provider plan and credentials before apply.",
        'terraform {',
        '  required_version = ">= 1.10.0"',
        '  required_providers {',
        '    proxmox = {',
        '      source  = "bpg/proxmox"',
        '      version = "= 0.118.0"',
        '    }',
        '  }',
        '}',
        '',
        '# Authentication via PROXMOX_VE_* environment variables; no literals.',
        'provider "proxmox" {}',
        '',
    ]
    def q(s):
        return json.dumps(str(s), ensure_ascii=True)
    for g in guests:
        role = g["role"]
        out += [
            f'resource "proxmox_virtual_environment_container" "{role}" {{',
            f'  node_name    = {q(g["node"])}',
            f'  vm_id        = {g["vmid"]}',
            f'  description  = "tobe4home generated preview: {role}; approval required"',
            '  unprivileged = true',
            '  started      = false',
            '  start_on_boot = false',
            '  lifecycle {',
            '    prevent_destroy = true',
            '  }',
            '  cpu {',
            f'    cores = {g["cores"]}',
            '  }',
            '  memory {',
            f'    dedicated = {g["memory_mb"]}',
            '  }',
            '  disk {',
            f'    datastore_id = {q(g["storage"])}',
            f'    size         = {g["disk_gb"]}',
            '  }',
            '  initialization {',
            f'    hostname = {q(g["hostname"])}',
            '    dns {',
            f'      servers = [{q(g["dns_resolver"])}]',
            '    }',
            '    ip_config {',
            '      ipv4 {',
            '        address = "dhcp"',
            '      }',
            '    }',
            '  }',
            '  network_interface {',
            '    name    = "eth0"',
            f'    bridge  = {q(g["bridge"])}',
            '    firewall = true',
            '  }',
            '  operating_system {',
            f'    template_file_id = {q(g["template"])}',
            '    type = "centos"',
            '  }',
            '}',
            '',
        ]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--choices", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--tf", action="store_true", help="print OpenTofu preview instead")
    args = parser.parse_args(argv)
    try:
        plan = compile_plan(
            json.loads(args.site.read_text(encoding="utf-8")),
            json.loads(args.choices.read_text(encoding="utf-8")),
            json.loads(args.inventory.read_text(encoding="utf-8")))
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"PLAN REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.tf:
        sys.stdout.write(render_opentofu(plan))
    else:
        print(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
