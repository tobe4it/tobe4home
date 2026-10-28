#!/usr/bin/env bash
# The only supported clean-install entry point for the single-controller design.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALLER="$ROOT/bootstrap/single-controller.sh"
[[ -f "$INSTALLER" ]] || { echo "FAIL CLOSED: controller installer missing" >&2; exit 3; }
exec bash "$INSTALLER" "$@"
