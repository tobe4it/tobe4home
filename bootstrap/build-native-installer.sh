#!/usr/bin/env bash
# Guest-only: compile audited AnsibleForms installer 7.4.2 from exact upstream
# source commit with a one-function Node v26.12.1 selection override.
# This installer is SOURCE-MODIFIED, not the official published binary.
set -Eeuo pipefail
umask 077

EXPECTED_COMMIT="ae60b31742ee5bd6956f9bf9798fd5b5356ccf42"
PIN="v26.12.1"
DEST="/usr/local/bin/ansibleforms-installer"
PATCH="/var/lib/tobe4home/patch-node-pin.py"

[[ $EUID -eq 0 ]] || { echo "INSTALLER_SOURCE_BUILD_REFUSED: guest root required" >&2; exit 2; }
[[ "$(uname -m)" == "x86_64" ]] ||
  { echo "INSTALLER_SOURCE_BUILD_REFUSED: only audited linux amd64 supported" >&2; exit 2; }
[[ -r "$PATCH" ]] || { echo "INSTALLER_SOURCE_BUILD_REFUSED: exact patch missing" >&2; exit 2; }

# All build inputs are pinned. golang is installed only in isolated CT1001;
# Go 1.27.2 is selected exactly using the verified upstream Go toolchain.
dnf -y install golang git ca-certificates
command -v go >/dev/null || { echo "Missing Go compiler" >&2; exit 2; }

TMP="$(mktemp -d /var/tmp/tb4h-af-src.XXXXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT
SRC="$TMP/src"
git init -q "$SRC"
git -C "$SRC" remote add origin https://github.com/ansibleforms/installer.git
git -C "$SRC" fetch -q --depth 1 origin refs/tags/v7.4.2
git -C "$SRC" checkout -q --detach FETCH_HEAD
ACTUAL_COMMIT="$(git -C "$SRC" rev-parse HEAD)"
[[ "$ACTUAL_COMMIT" == "$EXPECTED_COMMIT" ]] || {
  echo "INSTALLER_SOURCE_BUILD_REFUSED: upstream tag commit changed" >&2
  exit 2
}
[[ "$(sed -n 's/^go //p' "$SRC/go.mod" | head -1)" == "1.27.2" ]] || {
  echo "INSTALLER_SOURCE_BUILD_REFUSED: unexpected upstream Go version" >&2
  exit 2
}

python3 "$PATCH" "$SRC/internal/native/native.go"
cd "$SRC"
export GOTOOLCHAIN=go1.27.2
export GOPROXY=https://proxy.golang.org
export GOSUMDB=sum.golang.org
export GOFLAGS=-mod=readonly
GO_USED="$(go env GOVERSION)"
[[ "$GO_USED" == "go1.27.2" ]] || {
  echo "INSTALLER_SOURCE_BUILD_REFUSED: wrong Go toolchain" >&2
  exit 2
}
go build -trimpath -buildvcs=false -o "$TMP/ansibleforms-installer" .
[[ -s "$TMP/ansibleforms-installer" ]] || {
  echo "INSTALLER_SOURCE_BUILD_REFUSED: binary absent" >&2
  exit 2
}
install -m 0755 "$TMP/ansibleforms-installer" "$DEST"
echo "ANSIBLEFORMS_INSTALLER_SOURCE_COMMIT=$ACTUAL_COMMIT"
echo "ANSIBLEFORMS_INSTALLER_NODE_PIN=$PIN"
echo "ANSIBLEFORMS_INSTALLER_PATCHED=YES (only latestNode override; upstream SHA-256 preserved)"
