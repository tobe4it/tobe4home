#!/usr/bin/env bash
# Reviewed Stage-1 installer: one new, unprivileged Ansible controller LXC.
# Explicit human approval on the Proxmox console; does not delete anything.
set -euo pipefail
umask 077

VMID=1001
BRIDGE=""
STORAGE=""
TEMPLATE_STORAGE="local"
DNS_SERVER=""
HOSTNAME="tb4h-ansible"
APPLY=0
for arg in "$@"; do
  case "$arg" in
    --bridge=*) BRIDGE="${arg#*=}" ;;
    --storage=*) STORAGE="${arg#*=}" ;;
    --template-storage=*) TEMPLATE_STORAGE="${arg#*=}" ;;
    --nameserver=*) DNS_SERVER="${arg#*=}" ;;
    --apply) APPLY=1 ;;
    *) echo "Usage: $0 --bridge=vmbrX --storage=STORAGE [--template-storage=local] [--nameserver=IP] [--apply]" >&2; exit 2 ;;
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
command -v pvesh >/dev/null
command -v python3 >/dev/null
command -v lxc-usernsexec >/dev/null

# Fail closed if cluster-level inventory cannot be read or parsed.
CLUSTER_JSON="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  { echo "STOP: cannot read cluster-wide VMID inventory" >&2; exit 2; }
python3 -c '
import json,sys
data=json.load(sys.stdin)
if not isinstance(data,list):
    raise SystemExit("Invalid cluster resource inventory")
if any(int(x.get("vmid",-1))==1001 for x in data if isinstance(x,dict)):
    raise SystemExit("STOP: VMID 1001 is allocated anywhere in the cluster")
' <<< "$CLUSTER_JSON" ||
  { echo "STOP: cluster-wide VMID check rejected install" >&2; exit 2; }

lxc-usernsexec -m u:0:100000:65536 -m g:0:100000:65536 -- id -u |
  grep -qx 0 || { echo "STOP: unprivileged user namespace unavailable" >&2; exit 2; }


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

# The internal DNS resolver has already been entered/detected and saved
# by Stage 0. Do not blindly inherit the Proxmox host's DNS resolver.
if [[ -z "$DNS_SERVER" ]]; then
  DNS_SERVER="$(pct exec 1000 -- python3 -c '
import ipaddress, json
from pathlib import Path
values = json.loads(Path("/var/lib/tobe4home/site.local.json").read_text())
address = ipaddress.ip_address(values.get("dns_resolver", ""))
if address.version != 4 or address.is_loopback or address.is_multicast:
    raise SystemExit(2)
if address.is_unspecified or address.is_link_local:
    raise SystemExit(2)
print(address)
' 2>/dev/null)" ||
    { echo "STOP: cannot read saved DNS from CT 1000; specify --nameserver=IP" >&2; exit 2; }
fi
python3 - "$DNS_SERVER" <<'PY' ||
  { echo "STOP: unsupported DNS server address" >&2; exit 2; }
import ipaddress, sys
try:
    addr = ipaddress.ip_address(sys.argv[1])
    if addr.version != 4 or addr.is_loopback or addr.is_unspecified:
        raise ValueError("unsupported")
    if addr.is_link_local or addr.is_multicast:
        raise ValueError("unsupported")
except ValueError:
    raise SystemExit(2)
PY

TEMPLATE="rockylinux-10-default_20251001_amd64.tar.xz"
pveam list "$TEMPLATE_STORAGE" |
  awk -v name="$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" '$1 == name {found=1} END {exit !found}' ||
  { echo "STOP: selected Rocky 10 template not cached" >&2; exit 2; }

echo "=== TOBE4HOME STAGE-1 CONTROLLER ==="
echo "New CT: $VMID ($HOSTNAME) | unprivileged | no autostart"
echo "Rootfs: $STORAGE:16 | cores: 2 | RAM: 2048 MiB"
echo "Bridge: $BRIDGE | DHCP | guest firewall enabled"
echo "Nameserver: $DNS_SERVER (operator-reviewed Stage-0 configuration)"
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
    --nameserver "$DNS_SERVER" \
    --description "tobe4home Stage-1 Ansible controller - under review"
)
echo "CREATED: CT $VMID"
pct start "$VMID"
echo "STARTED: CT $VMID"
# A DHCP IPv4 lease does not prove that the guest can resolve repo hosts.
# Never enter DNF if the nameserver is unavailable.
if ! pct exec "$VMID" -- getent ahostsv4 mirrors.rockylinux.org >/dev/null 2>&1; then
  echo "STOP: DNS for Rocky repositories failed in CT 1001" >&2
  echo "Run the dedicated resume-ansible-controller.sh after checking CT DNS" >&2
  exit 2
fi
pct exec "$VMID" -- dnf -y install ansible-core git openssh-clients openssh-server python3 iproute
pct exec "$VMID" -- systemctl enable --now sshd
pct exec "$VMID" -- ansible --version
pct exec "$VMID" -- systemctl is-system-running --wait || true
echo "STAGE-1 CONTROLLER PACKAGES READY: CT $VMID"
echo "Controller does not yet have deployment credentials or an inventory."
echo "Next gates: managed SSH identity, playbook checkout and controlled jobs."
