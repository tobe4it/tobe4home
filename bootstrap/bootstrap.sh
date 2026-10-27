#!/usr/bin/env bash
# tobe4home stage-0: create an isolated RHEL-compatible setup container.
# Deliberately no curl|sh, destructive reconfiguration or unattended deployments.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VMID="" TEMPLATE="" STORAGE="" BRIDGE="" SSH_KEY="" APPLY=0
HOSTNAME="tobe4home-setup"
MEMORY=1024 CORES=1 DISK=8 PORT=8765

usage() {
  cat <<'EOF'
tobe4home stage-0 bootstrap (Proxmox VE host)

Usage:
  bash bootstrap/bootstrap.sh --vmid ID --template STORAGE:vztmpl/FILE \
    --storage STORAGE --bridge BRIDGE --ssh-public-key /path/to/key.pub [--apply]

Without --apply this is a read-only validation and plan.
--apply creates ONE new unprivileged LXC, installs Python/SSH and starts
the local-only setup web application. It never edits an existing VM/CT.
The OS template must already be present on a Proxmox template storage.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --vmid|--template|--storage|--bridge|--ssh-public-key)
      (($# >= 2)) || die "Missing value for $1"
      case "$1" in
        --vmid) VMID="$2" ;; --template) TEMPLATE="$2" ;;
        --storage) STORAGE="$2" ;; --bridge) BRIDGE="$2" ;;
        --ssh-public-key) SSH_KEY="$2" ;;
      esac
      shift 2 ;;
    --apply) APPLY=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Run as root on the Proxmox VE node"
for cmd in pct pvesm pvesh ip python3; do
  command -v "$cmd" >/dev/null || die "Missing required command: $cmd"
done
[[ "$VMID" =~ ^[1-9][0-9]{2,8}$ ]] || die "Invalid VMID"
[[ "$TEMPLATE" =~ ^[a-zA-Z0-9_.-]+:vztmpl/[a-zA-Z0-9_.-]+$ ]] ||
  die "Template must be a storage volume such as local:vztmpl/rockylinux-10-....tar.zst"
[[ "$TEMPLATE" =~ :vztmpl/(rockylinux|almalinux)-(9|10)[a-zA-Z0-9_.-]*\.tar\.(gz|xz|zst)$ ]] ||
  die "Only predownloaded Rocky/AlmaLinux 9/10 LXC templates are accepted"
[[ "$STORAGE" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "Invalid rootfs storage identifier"
[[ "$BRIDGE" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "Invalid bridge name"
[[ -f "$SSH_KEY" && -r "$SSH_KEY" ]] || die "SSH public key not readable"
[[ "$(wc -l < "$SSH_KEY")" -eq 1 ]] || die "Use a single public key"
grep -Eq '^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]+( .*)?$' "$SSH_KEY" ||
  die "Invalid SSH public key"
[[ -f "$SCRIPT_DIR/wizard.py" && -f "$SCRIPT_DIR/wizard.service" && -f "$SCRIPT_DIR/sshd.conf" ]] ||
  die "Incomplete bootstrap checkout"
ip link show dev "$BRIDGE" >/dev/null 2>&1 || die "Network bridge does not exist"
TEMPLATE_PATH="$(pvesm path "$TEMPLATE")" || die "Unable to resolve template storage path"
[[ -f "$TEMPLATE_PATH" ]] || die "Template archive not found: $TEMPLATE"
RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  die "Unable to inspect cluster VMIDs (refusing to proceed)"
VMID_USED="$(python3 -c 'import json,sys; target=int(sys.argv[1]); print(int(any(int(r.get("vmid",-1))==target for r in json.load(sys.stdin))))' "$VMID" <<< "$RESOURCES")" ||
  die "Unable to parse cluster VMIDs"
[[ "$VMID_USED" == 0 ]] || die "VMID already allocated in Proxmox cluster"
printf 'Stage-0 preflight: PASS\nVMID: %s\nOS template: %s\nStorage: %s\nBridge: %s\n' \
  "$VMID" "$TEMPLATE" "$STORAGE" "$BRIDGE"
if ((APPLY == 0)); then
  echo "DRY RUN: no resources changed. Add --apply to create the setup LXC."
  exit 0
fi

echo "Creating a NEW unprivileged, non-autostarting LXC..."
pct create "$VMID" "$TEMPLATE" \
  --hostname "$HOSTNAME" --unprivileged 1 --onboot 0 \
  --memory "$MEMORY" --cores "$CORES" --swap 256 \
  --rootfs "${STORAGE}:${DISK}" \
  --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp,firewall=1" \
  --tags "tobe4home;bootstrap" \
  --description "tobe4home stage-0 setup wizard; no production deployment"
echo "Created CT $VMID. Failures after this point leave it intact for diagnosis."
pct start "$VMID"

# Installing only the small, necessary runtime; no Podman or Docker in stage-0.
pct exec "$VMID" -- dnf -y install python3 openssh-server shadow-utils
pct exec "$VMID" -- /usr/sbin/useradd --create-home --shell /bin/bash tobe4home
pct exec "$VMID" -- install -d -m 0700 -o tobe4home -g tobe4home /home/tobe4home/.ssh
pct push "$VMID" "$SSH_KEY" /home/tobe4home/.ssh/authorized_keys --user tobe4home --group tobe4home --perms 0600
pct exec "$VMID" -- install -d -m 0755 /opt/tobe4home
pct exec "$VMID" -- install -d -m 0700 -o tobe4home -g tobe4home /var/lib/tobe4home
pct push "$VMID" "$SCRIPT_DIR/wizard.py" /opt/tobe4home/wizard.py --perms 0644
pct push "$VMID" "$SCRIPT_DIR/wizard.service" /etc/systemd/system/tobe4home-wizard.service --perms 0644
pct exec "$VMID" -- install -d -m 0755 /etc/ssh/sshd_config.d
pct push "$VMID" "$SCRIPT_DIR/sshd.conf" /etc/ssh/sshd_config.d/90-tobe4home.conf --perms 0644
pct exec "$VMID" -- systemctl daemon-reload
pct exec "$VMID" -- systemctl enable --now sshd tobe4home-wizard.service
pct exec "$VMID" -- systemctl is-active --quiet tobe4home-wizard.service ||
  die "Wizard did not start; inspect journal with pct exec $VMID -- journalctl -u tobe4home-wizard"

cat <<EOF
STAGE-0 READY: CT $VMID
Wizard listens ONLY on CT loopback port $PORT (no public HTTP listener).
Find the guest's IPv4 address in the Proxmox UI or via:
  pct exec $VMID -- hostname -I

From your administration workstation, forward SSH through the Proxmox node:
  ssh -N -J <proxmox-ssh-user>@<proxmox-address> \
    -L $PORT:127.0.0.1:$PORT tobe4home@<guest-address>
Then open http://127.0.0.1:$PORT/ in your workstation browser.

The wizard stores a local, private INSTALLATION PLAN only.
It does not deploy other services or store credentials.
EOF
