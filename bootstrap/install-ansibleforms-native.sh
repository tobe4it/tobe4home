#!/usr/bin/env bash
# Guest-only stage, executed inside an unprivileged Rocky Linux 10 CT1001.
# Builds exact upstream v7.4.2 source, patching ONLY Node version selection.
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
# Build from a verified immutable upstream source commit, rather than use
# the official binary which chooses an unavailable Node 26 patch dynamically.
# The sole source patch fixes Node v26.12.1 selection; the original upstream
# SHA-256 manifest/download implementation is kept.
# This is a tobe4home SOURCE-PATCHED installer, not an upstream release.
bash /var/lib/tobe4home/build-native-installer.sh
[[ -x /usr/local/bin/ansibleforms-installer ]] ||
  { echo "Patched installer build did not produce executable" >&2; exit 2; }
echo "Installing pinned AnsibleForms 7.4.2 with official native/systemd runtime."
echo "Source-patched from verified upstream v7.4.2 commit; Node v26.12.1 fixed, official SHA-256 preserved."
# The upstream Go native installer uses os.MkdirAll(..., 0755) and unpacks
# release/runtime files as root. With inherited umask 077 those directories
# become 0700 and systemd's unprivileged ansibleforms user fails 200/CHDIR.
# Use standard umask 022 ONLY for the reviewed upstream install process:
# upstream explicitly writes its app.env/rte.env with 0640 and credentials
# with restricted modes; do not chmod any secrets or data directory here.
# No password on argv: upstream generates one and prints it on completion.
# Does not use Docker/Podman and does not receive Proxmox API credentials.
umask 022
export TOBE4HOME_NODE_VERSION=v26.12.1
exec /usr/local/bin/ansibleforms-installer install --yes \
  --version 7.4.2 --role controller --mode native --port 443 --lang de
