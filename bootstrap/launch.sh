#!/usr/bin/env bash
# One-command entry point for a reviewed checkout of tobe4home.
# Collects choices on the Proxmox host BEFORE a LXC exists.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP="$ROOT/bootstrap/bootstrap.sh"
NETWORKS="$ROOT/bootstrap/networks.py"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
heading() { printf '\n=== %s ===\n' "$*"; }
ask() {
  local prompt="$1" default="$2" result
  read -r -p "$prompt [$default]: " result || fail "Input cancelled"
  printf '%s' "${result:-$default}"
}
[[ $EUID -eq 0 ]] || fail "Launch this tool as root on a Proxmox VE host"
[[ -t 0 && -t 1 ]] || fail "Interactive terminal is required"
[[ -r "$BOOTSTRAP" && -r "$NETWORKS" ]] || fail "Incomplete checkout"
for cmd in git pct pvesh pvesm pveam python3 find; do
  command -v "$cmd" >/dev/null || fail "Missing required command: $cmd"
done

# Debian-installer-style dialogs whenever whiptail is already present.
# Do not change the Proxmox host or install extra packages implicitly.
# TOBE4HOME_INSTALLER_UI=text forces the existing portable terminal prompts.
if [[ "${TOBE4HOME_INSTALLER_UI:-auto}" != text ]]; then
  if command -v whiptail >/dev/null 2>&1 && [[ "${TERM:-dumb}" != dumb ]]; then
    [[ -r "$ROOT/bootstrap/installer-tui.sh" ]] ||
      fail "Text UI source is missing in checkout"
    exec bash "$ROOT/bootstrap/installer-tui.sh"
  elif [[ "${TOBE4HOME_INSTALLER_UI:-auto}" == whiptail ]]; then
    fail "whiptail unavailable (or TERM=dumb); use a capable terminal or text fallback"
  else
    printf '%s\n' 'Hinweis: whiptail ist nicht installiert – einfacher Textdialog wird verwendet.' >&2
    printf '%s\n' 'Für den Debian-ähnlichen Konsoleninstaller: apt install whiptail (nur nach eigener Freigabe).' >&2
  fi
fi

cat <<'EOF'
tobe4home | Guided Proxmox bootstrap (stage 0)

This prototype creates ONE new unprivileged Rocky Linux 10 setup LXC,
after you inspect its plan and explicitly approve the installation.
No existing guest is reconfigured. The future web wizard records a draft;
it cannot deploy Forgejo, Ansible or other platform services yet.
EOF
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'Git revision: %s\n' "$(git -C "$ROOT" rev-parse --verify HEAD)"
  if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
    fail "Tracked files are modified locally; review checkout before running"
  fi
fi

heading "1/5 · Free Proxmox VMID"
RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  fail "Cannot read VM/CT allocation"
SUGGESTED_ID="$(python3 -c '
import json,sys
used={int(x["vmid"]) for x in json.load(sys.stdin) if "vmid" in x}
print(next((i for i in range(1000,2000) if i not in used),""))
' <<< "$RESOURCES")" || fail "Invalid Proxmox resource response"
[[ -n "$SUGGESTED_ID" ]] || fail "No unused VMID in preferred 1000–1999 range"
VMID="$(ask "Container VMID (1000–1999 suggested, override allowed)" "$SUGGESTED_ID")"
[[ "$VMID" =~ ^[1-9][0-9]{2,8}$ ]] || fail "Invalid VMID"
if python3 -c '
import json,sys
id=int(sys.argv[1])
sys.exit(0 if any(int(x.get("vmid",-1))==id for x in json.load(sys.stdin)) else 1)
' "$VMID" <<< "$RESOURCES"; then
  fail "VMID already in use"
fi

heading "2/5 · Container hostname prefix"
echo "The default prefix is tobe4home-; the setup guest will be PREFIX-setup."
PREFIX="$(ask "Hostname prefix (can be changed)" "tobe4home-")"
PREFIX="${PREFIX%-}"
[[ "$PREFIX" =~ ^[a-z]([a-z0-9-]*[a-z0-9])?$ ]] ||
  fail "Prefix must be a lowercase DNS label (letters, digits, internal hyphens)"
(( ${#PREFIX} <= 57 )) || fail "Prefix is too long"
printf 'Planned hostname: %s-setup\n' "$PREFIX"

heading "3/5 · Root filesystem storage"
pvesm status || fail "Cannot list Proxmox storage"
echo "Select active rootdir-capable storage. The template archive uses local."
STORAGE="$(ask "LXC rootfs storage" "local-zfs")"
[[ "$STORAGE" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail "Invalid storage identifier"

heading "4/5 · Network and optional VLAN"
echo "Select an infrastructure/management-accessible network."
echo "The Proxmox bridge name is NOT its VLAN ID. No network purpose is inferred."
NETWORK_SELECTION="$(python3 "$NETWORKS" --select)" ||
  fail "Network selection cancelled or unsupported"
read -r BRIDGE VLAN <<< "$NETWORK_SELECTION"
[[ "$BRIDGE" =~ ^vmbr[0-9]+$ ]] || fail "Network selection returned invalid bridge"
ARGS=(--vmid "$VMID" --storage "$STORAGE" --container-prefix "$PREFIX"
  --bridge "$BRIDGE")
if [[ "$VLAN" != "-" ]]; then
  [[ "$VLAN" =~ ^[0-9]+$ ]] || fail "Invalid network VLAN"
  ARGS+=(--vlan-tag "$VLAN")
fi

heading "5/5 · Public SSH key"
echo "Use the public key whose PRIVATE counterpart is on your admin workstation."
echo "Do NOT use a host-only key whose private counterpart cannot be accessed."
if [[ -d /root/.ssh ]]; then
  find /root/.ssh -maxdepth 1 -type f -name '*.pub' -print
fi
KEY="$(ask "Public SSH key file path" "/root/.ssh/id_ed25519.pub")"
[[ -r "$KEY" ]] || fail "Public SSH key missing or unreadable"
ARGS+=(--ssh-public-key "$KEY")
echo "OS: Rocky Linux 10 (official Proxmox catalog; auto-download on apply)"
echo "Template storage: local"

heading "READ-ONLY PREVIEW – no downloads and no guest changes"
bash "$BOOTSTRAP" "${ARGS[@]}"

printf '\n%s\n' 'Stage 0 will download Rocky Linux 10 if needed, create ONE guest,'
printf '%s\n' 'and install only SSH, Python and the local-only setup web app.'
printf '%s\n' 'The code is a prototype pending real Proxmox acceptance tests.'
printf '\nTo proceed, type exactly: INSTALL %s\n' "$VMID"
read -r -p '> ' APPROVAL || fail "Approval input cancelled"
if [[ "$APPROVAL" != "INSTALL $VMID" ]]; then
  echo "Cancelled. No bootstrap write actions were performed."
  exit 0
fi

heading "APPROVED STAGE-0 INSTALLATION"
bash "$BOOTSTRAP" "${ARGS[@]}" --apply
