#!/usr/bin/env bash
# Guest-only stage, executed inside an unprivileged Rocky Linux 10 CT1001.
# Downloads the exact AnsibleForms installer release and verifies SHA-256.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "Requires root inside CT1001" >&2; exit 2; }
grep -q '^ID="rocky"' /etc/os-release || grep -q '^ID=rocky$' /etc/os-release ||
  { echo "Not Rocky Linux" >&2; exit 2; }
command -v curl >/dev/null
command -v sha256sum >/dev/null
[[ "$(uname -m)" == "x86_64" ]] || { echo "Only reviewed AMD64 release" >&2; exit 2; }
if systemctl is-active --quiet ansibleforms &&
   systemctl is-active --quiet ansibleforms-rte; then
  echo "AnsibleForms already active: no reinstall"
  /usr/local/bin/ansibleforms-installer status
  exit 0
fi
if [[ -e /etc/ansibleforms/installer.json ]]; then
  echo "Existing AnsibleForms installer state requires operator review" >&2
  exit 3
fi
WORK="$(mktemp -d /var/tmp/tb4h-anforms.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
cd "$WORK"
BASE="https://github.com/ansibleforms/installer/releases/download/v7.4.2"
BIN="ansibleforms-installer_linux_amd64"
curl -fLsS --retry 3 --connect-timeout 20 -o "$BIN" "$BASE/$BIN"
curl -fLsS --retry 3 --connect-timeout 20 -o checksums.txt "$BASE/checksums.txt"
# Check only the selected architecture, not all binaries listed in checksums.txt.
awk -v n="$BIN" '$2==n || $2=="*"n {print}' checksums.txt > selected.sha256
[[ "$(wc -l < selected.sha256)" == 1 ]] ||
  { echo "No unique SHA256 for pinned installer" >&2; exit 2; }
sha256sum --check --status selected.sha256 ||
  { echo "AnsibleForms installer SHA256 mismatch" >&2; exit 2; }
install -m 0750 "$BIN" /usr/local/bin/ansibleforms-installer
echo "Installing pinned AnsibleForms 7.4.2 with official native/systemd runtime."
echo "Upstream installer handles MariaDB, Node.js, Python and independent Ansible RTE."
# The upstream Go native installer uses os.MkdirAll(..., 0755) and unpacks
# release/runtime files as root. With inherited umask 077 those directories
# become 0700 and systemd's unprivileged ansibleforms user fails 200/CHDIR.
# Use standard umask 022 ONLY for the reviewed upstream install process:
# upstream explicitly writes its app.env/rte.env with 0640 and credentials
# with restricted modes; do not chmod any secrets or data directory here.
# No password on argv: upstream generates one and prints it on completion.
# Does not use Docker/Podman and does not receive Proxmox API credentials.
umask 022
exec /usr/local/bin/ansibleforms-installer install --yes \
  --version 7.4.2 --role controller --mode native --port 443 --lang de
