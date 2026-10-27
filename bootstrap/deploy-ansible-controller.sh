#!/usr/bin/env bash
# Reviewed Stage-1 installer: one new, unprivileged Ansible controller LXC.
# Explicit human approval on the Proxmox console; does not delete anything.
set -euo pipefail
umask 077

VMID=1001
BRIDGE=""
STORAGE=""
TEMPLATE_STORAGE="local"
HOSTNAME="tb4h-ansible"
APPLY=0
for arg in "$@"; do
  case "$arg" in
    --bridge=*) BRIDGE="${arg#*=}" ;;
    --storage=*) STORAGE="${arg#*=}" ;;
    --template-storage=*) TEMPLATE_STORAGE="${arg#*=}" ;;
    --apply) APPLY=1 ;;
    *) echo "Usage: $0 --bridge=vmbrX --storage=STORAGE [--template-storage=local] [--apply]" >&2; exit 2 ;;
  esac
done
[[ "$EUID" -eq 0 ]] || { echo "Must run as root on Proxmox" >&2; exit 2; }
[[ "$BRIDGE" =~ ^vmbr[0-9]+$ ]] || { echo "Missing/invalid --bridge" >&2; exit 2; }
[[ "$STORAGE" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] ||
  { echo "Missing/invalid --storage" >&2; exit 2; }
[[ "$TEMPLATE_STORAGE" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] ||
  { echo "Invalid template storage" >&2; exit 2; }

command -v pct >/dev/null
command -v pvesm >/dev/null
command -v pveam >/dev/null

if pct config "$VMID" >/dev/null 2>&1; then
  echo "STOP: CT $VMID already exists" >&2; exit 2
fi
if [[ -d "/var/lib/lxc/$VMID" ]]; then
  echo "STOP: leftover CT directory for $VMID needs operator review" >&2; exit 2
fi
if pvesm list "$STORAGE" --content rootdir |
  awk -v id="$VMID" 'NR>1 && $1 ~ (":subvol-"id"-disk-") {found=1} END {exit !found}'; then
  echo "STOP: storage already contains rootfs for $VMID" >&2; exit 2
fi
pvesm status --content rootdir |
  awk -v name="$STORAGE" 'NR>1 && $1==name && $3=="active" {found=1} END {exit !found}' ||
  { echo "STOP: rootfs storage inactive/incompatible" >&2; exit 2; }

[[ -d "/sys/class/net/$BRIDGE/bridge" ]] ||
  { echo "STOP: selected bridge does not exist" >&2; exit 2; }

TEMPLATE="rockylinux-10-default_20251001_amd64.tar.xz"
pveam list "$TEMPLATE_STORAGE" |
  awk -v name="$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" '$1 == name {found=1} END {exit !found}' ||
  { echo "STOP: selected Rocky 10 template not cached" >&2; exit 2; }

echo "=== TOBE4HOME STAGE-1 CONTROLLER ==="
echo "New CT: $VMID ($HOSTNAME) | unprivileged | no autostart"
echo "Rootfs: $STORAGE:16 | cores: 2 | RAM: 2048 MiB"
echo "Bridge: $BRIDGE | DHCP | guest firewall enabled"
echo "Template: $TEMPLATE_STORAGE:vztmpl/$TEMPLATE"
echo "Action: create + start CT 1001; install ansible-core/git/SSH via DNF"
echo "No changes to any existing guest. No automatic cleanup on failure."

if (( ! APPLY )); then
  echo "READ-ONLY: repeat with --apply after reviewing this exact plan"
  exit 0
fi
read -r -p "Type DEPLOY 1001 to approve creation: " CONFIRM
[[ "$CONFIRM" == "DEPLOY 1001" ]] ||
  { echo "Cancelled; no guest created"; exit 2; }

# Proxmox uid-mapped tar extraction requires traversable transient rootfs;
# never propagate the Bootstrap's umask 077 to pct create.
(
  umask 022
  pct create "$VMID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$HOSTNAME" --unprivileged 1 --onboot 0 \
    --memory 2048 --cores 2 --swap 256 \
    --rootfs "$STORAGE:16" \
    --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp,firewall=1" \
    --description "tobe4home Stage-1 Ansible controller - under review"
)
echo "CREATED: CT $VMID"
pct start "$VMID"
echo "STARTED: CT $VMID"
pct exec "$VMID" -- dnf -y install ansible-core git openssh-clients python3 iproute
pct exec "$VMID" -- ansible --version
pct exec "$VMID" -- systemctl is-system-running --wait || true
echo "STAGE-1 CONTROLLER PACKAGES READY: CT $VMID"
echo "Controller does not yet have deployment credentials or an inventory."
echo "Next gates: managed SSH identity, playbook checkout and controlled jobs."
