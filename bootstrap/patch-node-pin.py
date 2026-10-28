#!/usr/bin/env python3
"""Patch precisely ONE upstream AnsibleForms installer v7.4.2 Node selector.

Source and commit are separately verified by build-native-installer.sh.
The upstream integrity-checked Node.js download remains entirely unchanged.
Do not accept an arbitrary source, patch version or ambiguous text location.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import sys

PIN = "v26.12.1"
TARGET = (
    'func latestNode(ctx context.Context, major string) (string, error) {\n'
    '\tindex, err := getText(ctx, "https://nodejs.org/dist/index.json")'
)
PATCH = (
    'func latestNode(ctx context.Context, major string) (string, error) {\n'
    '\tif pin := os.Getenv("TOBE4HOME_NODE_VERSION"); pin != "" {\n'
    '\t\tif pin != "v26.12.1" || major != "26" {\n'
    '\t\t\treturn "", fmt.Errorf("unsupported tobe4home pinned Node.js version")\n'
    '\t\t}\n'
    '\t\treturn pin, nil\n'
    '\t}\n'
    '\tindex, err := getText(ctx, "https://nodejs.org/dist/index.json")'
)


def patch_source(source: str) -> str:
    if source.count(TARGET) != 1:
        raise ValueError("Upstream selector is missing or ambiguous; refusing build")
    if "import (" not in source or '"os"' not in source or '"fmt"' not in source:
        raise ValueError("Expected upstream Go imports unavailable")
    if "func installNode(" not in source or 'base := "https://nodejs.org/dist/" + version + "/"' not in source:
        raise ValueError("Expected integrity-checking Node download path unavailable")
    if 'fetchSum(ctx, base+name+".tar.gz", sum, tmp, 1)' not in source:
        raise ValueError("Expected upstream SHA-256 download validation unavailable")
    if "TOBE4HOME_NODE_VERSION" in source:
        raise ValueError("Upstream source already contains a custom Node override")
    return source.replace(TARGET, PATCH, 1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.source.name != "native.go" or args.source.parent.name != "native":
            raise ValueError("Not the audited internal/native/native.go source")
        old = args.source.read_text(encoding="utf-8")
        new = patch_source(old)
        args.source.write_text(new, encoding="utf-8")
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"INSTALLER_NODE_PATCH_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"ANSIBLEFORMS_NODE_PIN_APPLIED={PIN} (original SHA-256 download preserved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
