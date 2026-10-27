#!/usr/bin/env bash
# tobe4home stage-0: create an isolated RHEL-compatible setup container.
# Deliberately no curl|sh, destructive reconfiguration or unattended deployments.
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VMID="" TEMPLATE="auto" TEMPLATE_STORAGE="local" STORAGE="" BRIDGE="" VLAN_TAG="" SSH_KEY="" APPLY=0
CONTAINER_PREFIX="tobe4home" PREFIX_EXPLICIT=0
HOSTNAME=""
MEMORY=1024 CORES=1 DISK=8 PORT=8765

usage() {
  cat <<'EOF'
tobe4home stage-0 bootstrap (Proxmox VE host)

Usage:
  bash bootstrap/bootstrap.sh --vmid ID --storage ROOTFS_STORAGE \
    --ssh-public-key /path/to/key.pub [--template-storage local] \
    [--template auto|STORAGE:vztmpl/FILE] [--bridge vmbrN] \
    [--vlan-tag 1..4094] [--container-prefix PREFIX] [--apply]

The official Rocky Linux 10 template is automatically discovered and, after
--apply, downloaded if missing. Omit --bridge for interactive bridge/VLAN choice.

Without --apply this is a read-only validation and plan.
--apply creates ONE new unprivileged LXC, installs Python/SSH and starts
the local-only setup web application. It never edits an existing VM/CT.
The default hostname prefix "tobe4home-" is a suggestion, not mandatory.
The --container-prefix option overrides it; the setup guest uses PREFIX-setup.
The official Rocky Linux 10 template is discovered from the Proxmox catalog.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --vmid|--template|--template-storage|--storage|--bridge|--vlan-tag|--container-prefix|--ssh-public-key)
      (($# >= 2)) || die "Missing value for $1"
      case "$1" in
        --vmid) VMID="$2" ;; --template) TEMPLATE="$2" ;;
        --template-storage) TEMPLATE_STORAGE="$2" ;; --vlan-tag) VLAN_TAG="$2" ;;
        --container-prefix) CONTAINER_PREFIX="$2"; PREFIX_EXPLICIT=1 ;;
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
for cmd in pct pvesm pvesh pveam ip python3; do
  command -v "$cmd" >/dev/null || die "Missing required command: $cmd"
done
[[ "$VMID" =~ ^[1-9][0-9]{2,8}$ ]] || die "Invalid VMID"
# Suggest, but never impose, a prefix. Hostnames for subsequent guests may be
# changed independently in the wizard; editing them never renames this setup CT.
if (( PREFIX_EXPLICIT == 0 )) && [[ -t 0 ]]; then
  read -r -p 'LXC hostname prefix [tobe4home-]: ' PREFIX_INPUT ||
    die "Prefix prompt cancelled"
  if [[ -n "$PREFIX_INPUT" ]]; then
    CONTAINER_PREFIX="$PREFIX_INPUT"
  fi
fi
# Accept a common trailing separator, store the normalized DNS label only.
CONTAINER_PREFIX="${CONTAINER_PREFIX%-}"
[[ "$CONTAINER_PREFIX" =~ ^[a-z]([a-z0-9-]*[a-z0-9])?$ ]] ||
  die "Prefix must contain lowercase ASCII letters, digits, and internal hyphens"
(( ${#CONTAINER_PREFIX} <= 57 )) ||
  die "Prefix too long: PREFIX-setup must be at most 63 characters"
HOSTNAME="${CONTAINER_PREFIX}-setup"
[[ "$TEMPLATE_STORAGE" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "Invalid template storage"
[[ "$STORAGE" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "Invalid rootfs storage identifier"
[[ -f "$SCRIPT_DIR/networks.py" ]] || die "Missing read-only network selection module"
if [[ "$TEMPLATE" != auto ]]; then
  [[ "$TEMPLATE" =~ ^[a-zA-Z0-9_.-]+:vztmpl/[a-zA-Z0-9_.-]+$ ]] ||
    die "Template must be STORAGE:vztmpl/FILE or auto"
  [[ "$TEMPLATE" =~ :vztmpl/(rockylinux|almalinux)-(9|10)[a-zA-Z0-9_.-]*\.tar\.(gz|xz|zst)$ ]] ||
    die "Only Rocky/Alma Linux 9/10 template filenames are accepted"
  TEMPLATE_STORAGE="${TEMPLATE%%:vztmpl/*}"
else
  # pveam available is read-only and uses the locally cached official catalog.
  CATALOG="$(pveam available --section system)" || die "Cannot read official Proxmox template catalog"
  TEMPLATE_FILE="$(printf '%s\n' "$CATALOG" |
    awk '$1 == "system" && $2 ~ /^rockylinux-10-default_[0-9]+_amd64\.tar\.(xz|zst|gz)$/ {print $2}' |
    LC_ALL=C sort | tail -n 1)"
  [[ -n "$TEMPLATE_FILE" ]] || die "No official Rocky Linux 10 template in catalog"
  TEMPLATE="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE_FILE}"
fi

if [[ -z "$BRIDGE" ]]; then
  [[ -z "$VLAN_TAG" ]] || die "Select a bridge when specifying --vlan-tag"
  [[ -t 0 ]] || die "No bridge selected; pass --bridge on noninteractive sessions"
  echo "Network selection (read-only discovery; no automatic VLAN recommendation):"
  NETWORK_SELECTION="$(python3 "$SCRIPT_DIR/networks.py" --select)" ||
    die "Network selection cancelled or invalid"
  read -r BRIDGE VLAN_SELECTION <<< "$NETWORK_SELECTION"
  [[ "$VLAN_SELECTION" == "-" ]] || VLAN_TAG="$VLAN_SELECTION"
fi
[[ "$BRIDGE" =~ ^vmbr[0-9]+$ ]] || die "Invalid Proxmox bridge name"
if [[ -n "$VLAN_TAG" ]]; then
  [[ "$VLAN_TAG" =~ ^[1-9][0-9]{0,3}$ ]] || die "Invalid VLAN tag"
  (( VLAN_TAG >= 1 && VLAN_TAG <= 4094 )) || die "VLAN tag must be 1..4094"
  python3 "$SCRIPT_DIR/networks.py" --validate "$BRIDGE" --tag "$VLAN_TAG" ||
    die "Bridge/VLAN pairing not verified"
else
  python3 "$SCRIPT_DIR/networks.py" --validate "$BRIDGE" ||
    die "Bridge not verified"
fi
[[ -f "$SSH_KEY" && -r "$SSH_KEY" ]] || die "SSH public key not readable"
[[ "$(wc -l < "$SSH_KEY")" -eq 1 ]] || die "Use a single public key"
grep -Eq '^(ssh-ed25519|ecdsa-sha2-nistp256|ssh-rsa) [A-Za-z0-9+/=]+( .*)?
[[ -f "$SCRIPT_DIR/wizard.py" && -f "$SCRIPT_DIR/wizard.service" && -f "$SCRIPT_DIR/sshd.conf" ]] ||
  die "Incomplete bootstrap checkout"
# The selected template must be present in the catalog OR already cached.
TEMPLATE_FILE="${TEMPLATE#*:vztmpl/}"
# A missing (not-yet-downloaded) template may make 'pvesm path' fail.
# Preview must remain valid and read-only even when the archive is absent.
TEMPLATE_PATH="$(pvesm path "$TEMPLATE" 2>/dev/null || true)"
TEMPLATE_CACHED=0
if [[ -n "$TEMPLATE_PATH" && -s "$TEMPLATE_PATH" ]]; then
  TEMPLATE_CACHED=1
else
  CATALOG="${CATALOG:-$(pveam available --section system)}" ||
    die "Cannot read official Proxmox template catalog"
  awk -v name="$TEMPLATE_FILE" '$1 == "system" && $2 == name {found=1} END {exit !found}' \
    <<< "$CATALOG" || die "Template not cached and not in official pveam catalog"
fi
RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  die "Unable to inspect cluster VMIDs (refusing to proceed)"
VMID_USED="$(python3 -c 'import json,sys; target=int(sys.argv[1]); print(int(any(int(r.get("vmid",-1))==target for r in json.load(sys.stdin))))' "$VMID" <<< "$RESOURCES")" ||
  die "Unable to parse cluster VMIDs"
[[ "$VMID_USED" == 0 ]] || die "VMID already allocated in Proxmox cluster"
printf 'Stage-0 preflight: PASS\nVMID: %s\nOS template: %s\nCached: %s\nRootfs: %s\nBridge: %s\nVLAN: %s\n' \
  "$VMID" "$TEMPLATE" "$([[ "$TEMPLATE_CACHED" -eq 1 ]] && echo yes || echo no)" \
  "$STORAGE" "$BRIDGE" "${VLAN_TAG:-untagged}"
printf 'Suggested hostname prefix: %s-\nStage-0 hostname: %s\n' "$CONTAINER_PREFIX" "$HOSTNAME"
if ((APPLY == 0)); then
  echo "DRY RUN: no resources changed. Add --apply to create the setup LXC."
  exit 0
fi

if (( TEMPLATE_CACHED == 0 )); then
  echo "Updating official Proxmox template catalog (approved apply phase)..."
  pveam update || die "Failed to refresh official template catalog"
  UPDATED_CATALOG="$(pveam available --section system)" ||
    die "Cannot read refreshed Proxmox catalog"
  awk -v name="$TEMPLATE_FILE" '$1 == "system" && $2 == name {found=1} END {exit !found}' \
    <<< "$UPDATED_CATALOG" ||
    die "Requested template disappeared from official catalog"
  echo "Downloading official catalog template $TEMPLATE_FILE to $TEMPLATE_STORAGE..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_FILE" ||
    die "Template download failed; no CT created"
  TEMPLATE_PATH="$(pvesm path "$TEMPLATE")" ||
    die "Unable to resolve freshly downloaded template"
  [[ -s "$TEMPLATE_PATH" ]] || die "Downloaded template not readable; no CT created"
fi
# Recheck occupancy after download, as it may take time.
RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  die "Cannot recheck cluster VMIDs"
VMID_USED="$(python3 -c 'import json,sys; target=int(sys.argv[1]); print(int(any(int(r.get("vmid",-1))==target for r in json.load(sys.stdin))))' "$VMID" <<< "$RESOURCES")" ||
  die "Cannot recheck VMIDs"
[[ "$VMID_USED" == 0 ]] || die "VMID was allocated during download"
python3 "$SCRIPT_DIR/networks.py" --validate "$BRIDGE" ${VLAN_TAG:+--tag "$VLAN_TAG"} ||
  die "Selected bridge/VLAN changed during download"
NETWORK_ARGS="name=eth0,bridge=${BRIDGE},ip=dhcp,firewall=1"
[[ -z "$VLAN_TAG" ]] || NETWORK_ARGS+=",tag=${VLAN_TAG}"
echo "Creating a NEW unprivileged, non-autostarting LXC..."
pct create "$VMID" "$TEMPLATE" \
  --hostname "$HOSTNAME" --unprivileged 1 --onboot 0 \
  --memory "$MEMORY" --cores "$CORES" --swap 256 \
  --rootfs "${STORAGE}:${DISK}" \
  --net0 "$NETWORK_ARGS" \
  --tags "tobe4home;bootstrap" \
  --description "tobe4home stage-0 setup wizard; no production deployment"
echo "Created CT $VMID. Failures after this point leave it intact for diagnosis."
pct start "$VMID"

# Installing only the small, necessary runtime; no Podman or Docker in stage-0.
pct exec "$VMID" -- dnf -y install python3 openssh-server shadow-utils
pct exec "$VMID" -- /usr/sbin/useradd --create-home --shell /bin/bash tobe4home
pct exec "$VMID" -- install -d -m 0700 -o tobe4home -g tobe4home /home/tobe4home/.ssh
pct push "$VMID" "$SSH_KEY" /home/tobe4home/.ssh/authorized_keys --user tobe4home --group tobe4home --perms 0600
pct exec "$VMID" -- install -d -m 0755 /etc/tobe4home
# Whitelisted DNS-label input only. Keep the selected bootstrap prefix available
# as an editable suggestion for *future* guest names in the setup wizard.
printf 'TOBE4HOME_CONTAINER_PREFIX=%s\n' "$CONTAINER_PREFIX" |
  pct exec "$VMID" -- tee /etc/tobe4home/bootstrap.env >/dev/null
pct exec "$VMID" -- chmod 0644 /etc/tobe4home/bootstrap.env
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
 "$SSH_KEY" ||
  die "Invalid SSH public key"
command -v ssh-keygen >/dev/null || die "ssh-keygen is required for public-key validation"
ssh-keygen -lf "$SSH_KEY" >/dev/null 2>&1 ||
  die "OpenSSH rejected the selected public key"
[[ -f "$SCRIPT_DIR/wizard.py" && -f "$SCRIPT_DIR/wizard.service" && -f "$SCRIPT_DIR/sshd.conf" ]] ||
  die "Incomplete bootstrap checkout"
# The selected template must be present in the catalog OR already cached.
TEMPLATE_FILE="${TEMPLATE#*:vztmpl/}"
# A missing (not-yet-downloaded) template may make 'pvesm path' fail.
# Preview must remain valid and read-only even when the archive is absent.
TEMPLATE_PATH="$(pvesm path "$TEMPLATE" 2>/dev/null || true)"
TEMPLATE_CACHED=0
if [[ -n "$TEMPLATE_PATH" && -s "$TEMPLATE_PATH" ]]; then
  TEMPLATE_CACHED=1
else
  CATALOG="${CATALOG:-$(pveam available --section system)}" ||
    die "Cannot read official Proxmox template catalog"
  awk -v name="$TEMPLATE_FILE" '$1 == "system" && $2 == name {found=1} END {exit !found}' \
    <<< "$CATALOG" || die "Template not cached and not in official pveam catalog"
fi
RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  die "Unable to inspect cluster VMIDs (refusing to proceed)"
VMID_USED="$(python3 -c 'import json,sys; target=int(sys.argv[1]); print(int(any(int(r.get("vmid",-1))==target for r in json.load(sys.stdin))))' "$VMID" <<< "$RESOURCES")" ||
  die "Unable to parse cluster VMIDs"
[[ "$VMID_USED" == 0 ]] || die "VMID already allocated in Proxmox cluster"
printf 'Stage-0 preflight: PASS\nVMID: %s\nOS template: %s\nCached: %s\nRootfs: %s\nBridge: %s\nVLAN: %s\n' \
  "$VMID" "$TEMPLATE" "$([[ "$TEMPLATE_CACHED" -eq 1 ]] && echo yes || echo no)" \
  "$STORAGE" "$BRIDGE" "${VLAN_TAG:-untagged}"
printf 'Suggested hostname prefix: %s-\nStage-0 hostname: %s\n' "$CONTAINER_PREFIX" "$HOSTNAME"
if ((APPLY == 0)); then
  echo "DRY RUN: no resources changed. Add --apply to create the setup LXC."
  exit 0
fi

if (( TEMPLATE_CACHED == 0 )); then
  echo "Updating official Proxmox template catalog (approved apply phase)..."
  pveam update || die "Failed to refresh official template catalog"
  UPDATED_CATALOG="$(pveam available --section system)" ||
    die "Cannot read refreshed Proxmox catalog"
  awk -v name="$TEMPLATE_FILE" '$1 == "system" && $2 == name {found=1} END {exit !found}' \
    <<< "$UPDATED_CATALOG" ||
    die "Requested template disappeared from official catalog"
  echo "Downloading official catalog template $TEMPLATE_FILE to $TEMPLATE_STORAGE..."
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE_FILE" ||
    die "Template download failed; no CT created"
  TEMPLATE_PATH="$(pvesm path "$TEMPLATE")" ||
    die "Unable to resolve freshly downloaded template"
  [[ -s "$TEMPLATE_PATH" ]] || die "Downloaded template not readable; no CT created"
fi
# Recheck occupancy after download, as it may take time.
RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  die "Cannot recheck cluster VMIDs"
VMID_USED="$(python3 -c 'import json,sys; target=int(sys.argv[1]); print(int(any(int(r.get("vmid",-1))==target for r in json.load(sys.stdin))))' "$VMID" <<< "$RESOURCES")" ||
  die "Cannot recheck VMIDs"
[[ "$VMID_USED" == 0 ]] || die "VMID was allocated during download"
python3 "$SCRIPT_DIR/networks.py" --validate "$BRIDGE" ${VLAN_TAG:+--tag "$VLAN_TAG"} ||
  die "Selected bridge/VLAN changed during download"
NETWORK_ARGS="name=eth0,bridge=${BRIDGE},ip=dhcp,firewall=1"
[[ -z "$VLAN_TAG" ]] || NETWORK_ARGS+=",tag=${VLAN_TAG}"
echo "Creating a NEW unprivileged, non-autostarting LXC..."
pct create "$VMID" "$TEMPLATE" \
  --hostname "$HOSTNAME" --unprivileged 1 --onboot 0 \
  --memory "$MEMORY" --cores "$CORES" --swap 256 \
  --rootfs "${STORAGE}:${DISK}" \
  --net0 "$NETWORK_ARGS" \
  --tags "tobe4home;bootstrap" \
  --description "tobe4home stage-0 setup wizard; no production deployment"
echo "Created CT $VMID. Failures after this point leave it intact for diagnosis."
pct start "$VMID"

# Installing only the small, necessary runtime; no Podman or Docker in stage-0.
pct exec "$VMID" -- dnf -y install python3 openssh-server shadow-utils
pct exec "$VMID" -- /usr/sbin/useradd --create-home --shell /bin/bash tobe4home
pct exec "$VMID" -- install -d -m 0700 -o tobe4home -g tobe4home /home/tobe4home/.ssh
pct push "$VMID" "$SSH_KEY" /home/tobe4home/.ssh/authorized_keys --user tobe4home --group tobe4home --perms 0600
pct exec "$VMID" -- install -d -m 0755 /etc/tobe4home
# Whitelisted DNS-label input only. Keep the selected bootstrap prefix available
# as an editable suggestion for *future* guest names in the setup wizard.
printf 'TOBE4HOME_CONTAINER_PREFIX=%s\n' "$CONTAINER_PREFIX" |
  pct exec "$VMID" -- tee /etc/tobe4home/bootstrap.env >/dev/null
pct exec "$VMID" -- chmod 0644 /etc/tobe4home/bootstrap.env
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
