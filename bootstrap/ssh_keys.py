#!/usr/bin/env python3
"""Discover administrative *public* SSH login keys for the stage-0 guest.

Only candidate public keys already in a user's authorized_keys are discovered.
The program never opens/copies private keys, and never uses the Proxmox host's
outbound identity key (*.pub) as evidence of an admin workstation identity.
Entries with authorized_keys options are excluded rather than silently
dropping the original restrictions when granting access to a new guest.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import sys

ALGORITHMS = {"ssh-ed25519", "ecdsa-sha2-nistp256", "ssh-rsa"}
LOGIN_RE = re.compile(r"^[a-z_][a-z0-9_-]*$", re.ASCII)


def normalized_key(raw: str) -> tuple[str, str, str]:
    """Return verified type, base64 body and OpenSSH SHA256 fingerprint."""
    if "\n" in raw.strip() or "\r" in raw.strip():
        raise ValueError("Exactly one public SSH key line is required")
    parts = raw.strip().split()
    if len(parts) < 2 or parts[0] not in ALGORITHMS:
        raise ValueError("Not a supported bare SSH public key")
    alg, blob = parts[:2]
    try:
        binary = base64.b64decode(blob, validate=True)
        if len(binary) < 8:
            raise ValueError("Truncated SSH public key")
        field_len = int.from_bytes(binary[:4], "big")
        if field_len != len(alg) or binary[4:4 + field_len] != alg.encode("ascii"):
            raise ValueError("SSH key algorithm and public blob disagree")
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Malformed SSH public key") from exc
    fp = base64.b64encode(hashlib.sha256(binary).digest()).decode("ascii").rstrip("=")
    return alg, blob, "SHA256:" + fp


def discover_from_sources(sources: list[tuple[str, Path]]) -> list[dict[str, str]]:
    """Read explicitly authorized login key sources. First source wins."""
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, path in sources:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, PermissionError, OSError, UnicodeError):
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Never remove from=, command=, restrict, etc. from an authorization.
            if line.split(maxsplit=1)[0] not in ALGORITHMS:
                continue
            try:
                algorithm, blob, fingerprint = normalized_key(line)
            except ValueError:
                continue
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            candidates.append({
                "index": str(len(candidates) + 1),
                "source": label,
                "algorithm": algorithm,
                "fingerprint": fingerprint,
                "key": algorithm + " " + blob,
            })
    return candidates


def discover(sudo_user: str | None = None) -> list[dict[str, str]]:
    """Prioritize the initiating sudo user, then the Proxmox root SSH login."""
    sources = []
    if sudo_user and sudo_user != "root" and LOGIN_RE.fullmatch(sudo_user):
        try:
            account = pwd.getpwnam(sudo_user)
            sources.append((f"{sudo_user}: authorized_keys",
                            Path(account.pw_dir) / ".ssh" / "authorized_keys"))
        except KeyError:
            pass
    sources.append(("root: Proxmox authorized_keys",
                    Path("/root/.ssh/authorized_keys")))
    # Some Proxmox configurations don't expose the usual root symlink.
    sources.append(("Proxmox cluster authorized_keys",
                    Path("/etc/pve/priv/authorized_keys")))
    return discover_from_sources(sources)


def store_key(destination: Path, raw: str) -> str:
    """Owner-only temporary public key file, exclusively created."""
    algorithm, blob, fingerprint = normalized_key(raw)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(f"{algorithm} {blob}\n")
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return fingerprint


def selected(candidates: list[dict[str, str]], fingerprint: str) -> dict[str, str]:
    match = next((c for c in candidates if c["fingerprint"] == fingerprint), None)
    if match is None:
        raise ValueError("The previously discovered key is no longer available")
    return match


def interactive_key(candidates: list[dict[str, str]]) -> str:
    print("Administrative SSH public keys in authorized_keys:", file=sys.stderr)
    for c in candidates:
        print(f' {c["index"]}. {c["source"]}: {c["algorithm"]} {c["fingerprint"]}',
              file=sys.stderr)
    print(" p. Paste your workstation/Termius PUBLIC key", file=sys.stderr)
    print(" f. Use a public-key file already available on this host", file=sys.stderr)
    print("Blank cancels without creating a guest.", file=sys.stderr)
    while True:
        choice = input("Choose the public key: ").strip()
        if not choice:
            raise ValueError("SSH key selection cancelled")
        if choice == "p":
            key = input("Paste exactly one SSH PUBLIC key line: ").strip()
            normalized_key(key)
            return key
        if choice == "f":
            path = input("Public key file path: ").strip()
            key = Path(path).read_text(encoding="utf-8").strip()
            normalized_key(key)
            return key
        matching = next((c for c in candidates if c["index"] == choice), None)
        if matching:
            print("Your administration device MUST possess the corresponding private key.",
                  file=sys.stderr)
            if input("Use this existing login key? [y/N]: ").strip().lower() in ("y", "yes"):
                return matching["key"]
        else:
            print("Invalid selection.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--list", action="store_true")
    choice.add_argument("--export", metavar="SHA256_FINGERPRINT")
    choice.add_argument("--from-stdin", action="store_true")
    choice.add_argument("--interactive", action="store_true")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        entries = discover(os.environ.get("SUDO_USER"))
        if args.list:
            # Never emit raw key material in the UI candidate listing.
            print(json.dumps([{k: v for k, v in e.items() if k != "key"}
                              for e in entries], ensure_ascii=False))
            return
        if args.destination is None:
            parser.error("--destination required for selection/export")
        if args.export:
            raw = selected(entries, args.export)["key"]
        elif args.from_stdin:
            raw = sys.stdin.read().strip()
        else:
            raw = interactive_key(entries)
        fingerprint = store_key(args.destination, raw)
        print(fingerprint)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
