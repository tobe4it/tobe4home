#!/usr/bin/env python3
"""Preflight the exact Node.js release AnsibleForms 7.4.2 will choose.

The upstream native installer uses the highest v<major> from nodejs.org
/dist/index.json then downloads that release's SHASUMS256.txt and the
linux-x64 .tar.gz. When the public index leads the files, installation
fails after creating a partially provisioned controller.

Read-only, fail-closed; does not download or replace any executable.
Never select an older version silently: upstream would still select
the highest indexed one. Only official nodejs.org HTTPS is queried.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://nodejs.org/dist/"
MAX_INDEX = 2_000_000
MAX_SUMS = 100_000
MAJOR = 26


def fetch_text(url: str, maxbytes: int) -> str:
    if not url.startswith(BASE):
        raise ValueError("Refusing untrusted Node.js download origin")
    with urlopen(Request(url, headers={"User-Agent": "tobe4home-node-preflight/1"}), timeout=15) as stream:
        if stream.status != 200:
            raise ValueError(f"Unexpected HTTP {stream.status} at official Node.js origin")
        data = stream.read(maxbytes + 1)
    if len(data) > maxbytes:
        raise ValueError("Official Node.js response exceeds size limit")
    return data.decode("utf-8")


def check_asset(url: str) -> None:
    if not url.startswith(BASE):
        raise ValueError("Refusing untrusted Node.js download origin")
    with urlopen(Request(url, method="HEAD", headers={"User-Agent": "tobe4home-node-preflight/1"}), timeout=20) as stream:
        if stream.status != 200:
            raise ValueError(f"Official Node.js archive HTTP {stream.status}")
        size = stream.headers.get("Content-Length")
        if size is not None and (not size.isdigit() or int(size) < 1_000_000):
            raise ValueError("Node.js archive is unexpectedly small")


def chosen_node_release(index: str, major: int = MAJOR) -> str:
    records = json.loads(index)
    if not isinstance(records, list):
        raise ValueError("Node.js version index has unexpected shape")
    # Match upstream latestNode behavior: highest semantic version,
    # not the first entry or any older version that happens to be available.
    candidate_versions: list[tuple[int, int, int]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        v = record.get("version")
        if not isinstance(v, str):
            continue
        m = re.fullmatch(r"v([0-9]+)\.([0-9]+)\.([0-9]+)", v)
        if m is not None and int(m.group(1)) == major:
            candidate_versions.append(tuple(map(int, m.groups())))
    if not candidate_versions:
        raise ValueError(f"No Node.js {major} release in official index")
    x, y, z = max(candidate_versions)
    return f"v{x}.{y}.{z}"


def verify_sums(sums: str, filename: str) -> None:
    matches = []
    for line in sums.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})\s+(\S+)", line.strip())
        if m and m.group(2) == filename:
            matches.append(m.group(1))
    if len(matches) != 1:
        raise ValueError(f"Official SHASUMS256.txt does not list exactly one {filename}")


PIN = "v26.12.1"


def check(major: int = MAJOR, pinned: str | None = None) -> str:
    if pinned is None:
        # Backward-compatible diagnostic of the original upstream dynamic
        # selection; never used for the tobe4home pinned install.
        version = chosen_node_release(fetch_text(BASE + "index.json", MAX_INDEX), major)
    else:
        if pinned != PIN or major != MAJOR:
            raise ValueError("Only reviewed Node v26.12.1 is supported")
        version = PIN
    base = f"{BASE}{version}/"
    filename = f"node-{version}-linux-x64.tar.gz"
    # The upstream downloads this exact checksum and archive.
    sums = fetch_text(base + "SHASUMS256.txt", MAX_SUMS)
    verify_sums(sums, filename)
    check_asset(base + filename)
    return version


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--major", type=int, default=MAJOR)
    p.add_argument("--pinned", default=PIN)
    args = p.parse_args()
    if args.major != MAJOR or args.pinned != PIN:
        print("NODE_PREFLIGHT_REFUSED: only audited Node.js v26.12.1", file=sys.stderr)
        return 2
    try:
        version = check(args.major, pinned=args.pinned)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        # Avoid printing potentially attacker-controlled URL response bodies.
        print(f"NODE_RUNTIME_NOT_READY: pinned official Node.js {PIN} checksum/archive not ready ({type(exc).__name__})", file=sys.stderr)
        print("Refusing this bootstrap before native AnsibleForms starts. Retry only after official release is complete.", file=sys.stderr)
        return 2
    print(f"NODE_RUNTIME_READY={version} (pinned; official SHASUMS256 and Linux x64 archive reachable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
