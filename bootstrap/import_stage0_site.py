#!/usr/bin/env python3
"""Derive a private planner site input from the existing Stage-0 wizard.

Read-only PVE host command. Only known nonsecret fields are copied from
CT 1000; unrelated wizard state is never persisted or printed.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys


def stage0_config():
    script = (
        "import json\n"
        "from pathlib import Path\n"
        "raw=json.loads(Path('/var/lib/tobe4home/site.local.json').read_text())\n"
        "print(json.dumps({"
        "'prefix':raw.get('container_prefix', 'tb4h'),"
        "'dns_resolver':raw.get('dns_resolver','')}))\n"
    )
    result = subprocess.run(
        ["pct", "exec", "1000", "--", "python3", "-c", script],
        capture_output=True, text=True, check=True, timeout=12)
    raw = json.loads(result.stdout)
    if not isinstance(raw, dict):
        raise ValueError("Invalid source configuration")
    return raw


def produce(source, *, node, bridge, storage, template, vmid_from=1002, vmid_to=1099):
    if not isinstance(source, dict):
        raise ValueError("Expected Stage-0 site configuration")
    prefix = source.get("prefix", "")
    dns_resolver = source.get("dns_resolver", "")
    # Independent validation by infra_planner follows; no site-local
    # arbitrary keys and no credential fields cross the boundary.
    import re
    if not isinstance(prefix, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", prefix):
        raise ValueError("Invalid Stage-0 prefix")
    ip = ipaddress.IPv4Address(dns_resolver)
    if ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local:
        raise ValueError("Stage-0 DNS cannot be used for new guests")
    return {
        "prefix": prefix, "node": node, "storage": storage,
        "bridge": bridge, "template": template, "dns_resolver": str(ip),
        "vmid_from": vmid_from, "vmid_to": vmid_to,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--storage", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--vmid-from", type=int, default=1002)
    parser.add_argument("--vmid-to", type=int, default=1099)
    args = parser.parse_args(argv)
    try:
        conf = produce(
            stage0_config(), node=args.node, bridge=args.bridge,
            storage=args.storage, template=args.template,
            vmid_from=args.vmid_from, vmid_to=args.vmid_to)
        # Also reuse the same strict identifier validation as the planner.
        from infra_planner import PVE_ID_RE, ID_RE, BRIDGE_RE, TEMPLATE_RE, check_id
        check_id(conf["prefix"], "prefix", ID_RE)
        check_id(conf["node"], "node")
        check_id(conf["storage"], "storage")
        check_id(conf["bridge"], "bridge", BRIDGE_RE)
        check_id(conf["template"], "template", TEMPLATE_RE)
        if conf["vmid_from"] < 100 or conf["vmid_to"] < conf["vmid_from"]:
            raise ValueError("Invalid VMID range")
    except (OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print("SITE IMPORT REFUSED:", str(exc)[:180], file=sys.stderr)
        return 2
    print(json.dumps(conf, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
