#!/usr/bin/env bash
# Proxmox-only single-controller installer. Never touches CT1000.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
VMID=1001
MODE=preview
BRIDGE="" STORAGE="" DNS="" KEY="" TSTORE=local
die() { echo "STOP: $*" >&2; exit 2; }
ask() {
  local answer=""
  read -r -p "$1: " answer || die "Input cancelled"
  printf '%s' "$answer"
}
usage() {
  cat <<'EOF'
Single Controller Clean Install (Proxmox -> CT1001 -> AnsibleForms 7.4.2)
  sudo bash bootstrap/launch.sh                            # interactive
  sudo bash bootstrap/launch.sh --bridge vmbr3 --storage local-zfs \
    --nameserver <DNS_IP> [--ssh-public-key <path>] [--apply]
  sudo bash bootstrap/launch.sh --resume                   # recover CT1001
Without --apply this is read-only. Apply requires INSTALL 1001.
Resume checks the existing tobe4home guest and requires RESUME 1001.
EOF
}
while (($#)); do
  case "$1" in
    --bridge|--storage|--nameserver|--ssh-public-key|--template-storage)
      (($# > 1)) || die "Missing $1 argument"
      case "$1" in
        --bridge) BRIDGE="$2";; --storage) STORAGE="$2";;
        --nameserver) DNS="$2";; --ssh-public-key) KEY="$2";;
        --template-storage) TSTORE="$2";;
      esac
      shift 2;;
    --apply) [[ "$MODE" == preview ]] || die "Conflicting modes"; MODE=apply; shift;;
    --resume) [[ "$MODE" == preview ]] || die "Conflicting modes"; MODE=resume; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown flag: $1";;
  esac
done
[[ $EUID -eq 0 ]] || die "Root on Proxmox required"
for cmd in pct pvesh pvesm pveam python3 lxc-usernsexec; do
  command -v "$cmd" >/dev/null || die "Missing Proxmox command: $cmd"
done
[[ -r "$ROOT/bootstrap/host_preflight.py" &&
   -r "$ROOT/bootstrap/networks.py" &&
   -r "$ROOT/bootstrap/ct1001_remnant.py" &&
   -r "$ROOT/bootstrap/install-ansibleforms-native.sh" &&
   -r "$ROOT/bootstrap/repair-ansibleforms-permissions.py" &&
   -r "$ROOT/bootstrap/check-controller-config.py" &&
   -r "$ROOT/bootstrap/show-first-login.py" &&
   -r "$ROOT/bootstrap/check-node-runtime.py" ]] ||
   die "Checkout incomplete"
if [[ "$MODE" != resume ]]; then
  echo "tobe4home – single Controller CT1001 (no CT1000)"
  if [[ -t 0 ]]; then
    [[ -n "$BRIDGE" ]] || BRIDGE="$(ask "Management bridge, e.g. vmbr3")"
    [[ -n "$STORAGE" ]] || STORAGE="$(ask "Rootfs storage, e.g. local-zfs")"
    [[ -n "$DNS" ]] || DNS="$(ask "Working IPv4 DNS server for guest")"
  fi
  [[ "$BRIDGE" =~ ^vmbr[0-9]{1,3}$ ]] || die "Invalid management bridge"
  [[ "$STORAGE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || die "Invalid storage"
  [[ "$TSTORE" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$ ]] || die "Invalid template storage"
  python3 - "$DNS" <<'PY' || die "DNS must be non-loopback IPv4"
import ipaddress,sys
try:
    ip=ipaddress.IPv4Address(sys.argv[1])
    assert not (ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast)
except (ValueError,AssertionError):
    raise SystemExit(2)
PY
  python3 "$ROOT/bootstrap/networks.py" --validate "$BRIDGE" ||
    die "Bridge not verified"
  python3 "$ROOT/bootstrap/host_preflight.py" --storage "$STORAGE" --vmid "$VMID" ||
    die "Rocky 10 host compatibility failed"
  # The official native AnsibleForms installer selects the newest Node 26
  # from nodejs.org/dist/index.json on each run. A newly indexed but not
  # yet published version (v26.13.0 observed 2026-10-28) leaves a broken
  # half-installed CT. Fail before VMID allocation, key selection or apply.
  echo "Verifying official Node.js runtime assets before creating CT1001..."
  python3 "$ROOT/bootstrap/check-node-runtime.py" --major 26 ||
    die "Upstream Node.js release incomplete; no CT1001 created"
  RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
    die "Cluster-wide inventory not available"
  python3 -c '
import json,sys
xs=json.load(sys.stdin)
assert isinstance(xs,list)
assert not any(int(x.get("vmid",-1))==1001 for x in xs if isinstance(x,dict))
' <<< "$RESOURCES" || die "VMID 1001 allocated"
  pct config "$VMID" >/dev/null 2>&1 && die "CT1001 already exists; use --resume"
  # Previous CT1001 can leave an empty runtime directory or the exact
  # generated rules.seccomp + empty passthrough bundle. Preflight WARNs
  # on those two known remnants only; unexpected contents still FAIL.
  # Nothing is removed or moved before INSTALL 1001 approval.
  if [[ -e /var/lib/lxc/1001 || -L /var/lib/lxc/1001 ]]; then
    [[ -d /var/lib/lxc/1001 && ! -L /var/lib/lxc/1001 ]] ||
      die "Unexpected CT1001 runtime path type"
    echo "NOTE: approved CT1001 runtime remnant detected; will rmdir if empty,"
    echo "or quarantine the exact Proxmox-generated artifacts after approval."
  fi
  TEMPLATE_FILE="$(pveam available --section system |
    awk '$1=="system" && $2 ~ /^rockylinux-10-default_[0-9]+_amd64\.tar\.(xz|gz|zst)$/ {print $2}' |
    LC_ALL=C sort | tail -n 1)"
  [[ -n "$TEMPLATE_FILE" ]] || die "Official Rocky Linux 10 template missing in catalog"
  TEMPLATE="$TSTORE:vztmpl/$TEMPLATE_FILE"
  CACHED=no
  TPATH="$(pvesm path "$TEMPLATE" 2>/dev/null || true)"
  [[ -n "$TPATH" && -s "$TPATH" ]] && CACHED=yes
  # Only ask for a key after host/VMID/storage preflight passes. An invalid
  # or stale LXC runtime path must not require repeated interactive selection.
  if [[ -z "$KEY" && -t 0 ]]; then
    echo "SSH-Administrationsschlüssel aus bestehenden Login-Schlüsseln wählen."
    KEY_TEMP_DIR="$(mktemp -d /run/tobe4home-key.XXXXXXXX)" ||
      die "Cannot create private key staging directory"
    chmod 0700 "$KEY_TEMP_DIR"
    trap 'rm -rf -- "$KEY_TEMP_DIR"' EXIT
    KEY="$KEY_TEMP_DIR/admin.pub"
    KEY_HELPER="$ROOT/bootstrap/ssh_keys.py"
    [[ -r "$KEY_HELPER" ]] || die "Missing public SSH key helper"
    python3 "$KEY_HELPER" --interactive --destination "$KEY" ||
      die "Public SSH key selection cancelled"
  fi
  if [[ -n "$KEY" ]]; then
    [[ -r "$KEY" ]] || die "Public key unreadable"
    [[ $(wc -l < "$KEY") == 1 ]] || die "Exactly one SSH public key required"
    ssh-keygen -lf "$KEY" >/dev/null || die "Invalid public key"
  fi
  cat <<PLAN

=== CT1001 PLAN (read-only) ===
New unprivileged Rocky 10 CT1001, hostname tb4h-controller, onboot=0
4 vCPU, RAM 4096 MiB, rootfs 40 GiB on $STORAGE
Bridge $BRIDGE, DHCP, firewall enabled, DNS $DNS
Template $TEMPLATE (cached: $CACHED)
AnsibleForms 7.4.2, native MariaDB/systemd and separate RTE.
Only this guest. No CT1000, no OpenTofu apply, no extra guests.
PLAN
  if [[ "$MODE" == preview ]]; then
    echo "PREVIEW ONLY. Run with --apply to create the reviewed CT."
    exit 0
  fi
  [[ -t 0 && -t 1 ]] || die "Apply requires interactive TTY"
  read -r -p 'Type INSTALL 1001 to approve: ' APPROVAL || die "Cancelled"
  [[ "$APPROVAL" == 'INSTALL 1001' ]] || die "Cancelled; nothing created"
  if [[ "$CACHED" == no ]]; then
    pveam update || die "Failed to refresh official templates"
    pveam download "$TSTORE" "$TEMPLATE_FILE" || die "Template download failed"
  fi
  RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
    die "Unable to recheck VMIDs"
  python3 -c '
import json,sys
xs=json.load(sys.stdin)
assert isinstance(xs,list)
assert not any(int(x.get("vmid",-1))==1001 for x in xs if isinstance(x,dict))
' <<< "$RESOURCES" || die "CT1001 became occupied"
  python3 "$ROOT/bootstrap/networks.py" --validate "$BRIDGE" || die "Bridge changed"
  # Recheck identity and rootfs inventory BEFORE removing even an empty
  # runtime remnant. If Proxmox cannot list storage, fail CLOSED.
  pct config "$VMID" >/dev/null 2>&1 &&
    die "CT1001 appeared during install"
  ROOTDIR_VOLUMES="$(pvesm list "$STORAGE" --content rootdir)" ||
    die "Cannot independently verify absence of CT1001 rootfs volumes"
  if awk 'NR>1 && $1 ~ /:subvol-1001-disk-/ {found=1} END {exit !found}' \
    <<< "$ROOTDIR_VOLUMES"; then
    die "CT1001 rootfs volume appeared; no guest created"
  fi
  # After explicit approval, remove only a truly empty directory using
  # rmdir. For the exact nonempty PVE residue, ATOMICALLY MOVE (not
  # delete) rules.seccomp + empty passthrough into a private quarantine.
  # Every unexpected file, mountpoint, symlink or changed state blocks.
  if [[ -e /var/lib/lxc/1001 || -L /var/lib/lxc/1001 ]]; then
    [[ -d /var/lib/lxc/1001 && ! -L /var/lib/lxc/1001 ]] ||
      die "CT1001 leftover is not a normal directory"
    if rmdir -- /var/lib/lxc/1001 2>/dev/null; then
      echo "REMOVED ONLY EMPTY RUNTIME DIRECTORY: /var/lib/lxc/1001"
    else
      python3 "$ROOT/bootstrap/ct1001_remnant.py" --quarantine-approved-ct1001 ||
        die "CT1001 runtime remnant is not eligible for safe quarantine"
    fi
  fi
  (
    umask 022
    pct create "$VMID" "$TEMPLATE" --hostname tb4h-controller \
      --unprivileged 1 --onboot 0 --cores 4 --memory 4096 --swap 512 \
      --rootfs "$STORAGE:40" \
      --net0 "name=eth0,bridge=$BRIDGE,firewall=1,ip=dhcp" \
      --nameserver "$DNS" --tags "tobe4home;controller" \
      --description "tobe4home single-controller test (AnsibleForms native)"
  )
  echo "CT1001 created; failures now preserve it for --resume."
  pct start "$VMID"
else
  [[ -t 0 && -t 1 ]] || die "Resume requires interactive TTY"
  CFG="$(pct config "$VMID")" || die "CT1001 does not exist"
  # Proxmox normalizes/sorts LXC tags (for example controller;tobe4home).
  # Check the exact tag *set* and other identity fields before accepting any
  # resume action, not an incidental substring order from pct create.
  python3 "$ROOT/bootstrap/check-controller-config.py" <<< "$CFG" ||
    die "Not the tobe4home controller"
  read -r -p 'Type RESUME 1001 to resume installation in this CT: ' APPROVAL ||
    die "Cancelled"
  [[ "$APPROVAL" == 'RESUME 1001' ]] || die "Cancelled"
  pct status "$VMID" | grep -q 'status: running' || pct start "$VMID"
fi

echo "Checking guest DNS for Rocky repositories..."
RESOLVED=0
for attempt in 1 2 3; do
  if pct exec "$VMID" -- getent ahostsv4 mirrors.rockylinux.org >/dev/null 2>&1; then
    RESOLVED=1; break
  fi
  [[ "$attempt" == 3 ]] || sleep 5
done
(( RESOLVED == 1 )) || die "Guest DNS failed; inspect guest and use --resume"
pct exec "$VMID" -- dnf -y install ca-certificates curl git python3 \
  openssh-server openssh-clients iproute openssl tar gzip ||
  die "Guest packages failed; use --resume"
pct exec "$VMID" -- systemctl enable --now sshd ||
  die "Guest SSH service failed; use --resume"
if [[ -n "$KEY" ]]; then
  pct exec "$VMID" -- id -u tb4h >/dev/null 2>&1 ||
    pct exec "$VMID" -- useradd --create-home --shell /bin/bash tb4h
  pct exec "$VMID" -- install -d -m 0700 -o tb4h -g tb4h /home/tb4h/.ssh
  pct push "$VMID" "$KEY" /home/tb4h/.ssh/authorized_keys \
    --user tb4h --group tb4h --perms 0600
fi
pct exec "$VMID" -- install -d -m 0700 /var/lib/tobe4home
pct push "$VMID" "$ROOT/bootstrap/install-ansibleforms-native.sh" \
  /var/lib/tobe4home/install-ansibleforms-native.sh --perms 0700
pct push "$VMID" "$ROOT/bootstrap/repair-ansibleforms-permissions.py" \
  /var/lib/tobe4home/repair-ansibleforms-permissions.py --perms 0700
# Keep the login reader INSIDE CT1001: no copy of the full app.env and no
# credentials in shell arguments, Git, host files, or systemd journals.
pct push "$VMID" "$ROOT/bootstrap/show-first-login.py" \
  /var/lib/tobe4home/show-first-login.py --perms 0700
pct push "$VMID" "$ROOT/bootstrap/check-node-runtime.py" \
  /var/lib/tobe4home/check-node-runtime.py --perms 0700
# Re-check through the guest network immediately before invoking native
# installer. A transient upstream index / mirror race must not be mistaken
# for a Proxmox issue or bypassed with an unverified Node tarball.
pct exec "$VMID" -- python3 /var/lib/tobe4home/check-node-runtime.py --major 26 ||
  die "Guest cannot fetch matching official Node runtime assets; CT1001 kept"
# A failed native installation can leave fully installed systemd units but
# inaccessible code directories due to a prior umask=077. --resume must
# recover those units, not rerun setup or replace the existing database,
# admin credentials, certificates, or stored settings.
if pct exec "$VMID" -- test -f /etc/systemd/system/ansibleforms.service &&
   pct exec "$VMID" -- test -f /etc/systemd/system/ansibleforms-rte.service; then
  echo "Existing native AnsibleForms services detected; repairing program access."
  pct exec "$VMID" -- python3 /var/lib/tobe4home/repair-ansibleforms-permissions.py --apply ||
    die "Native program permission validation refused; CT1001 preserved"
  pct exec "$VMID" -- systemctl reset-failed ansibleforms ansibleforms-rte ||
    die "Cannot reset failed AnsibleForms service states"
  pct exec "$VMID" -- systemctl restart ansibleforms-rte ansibleforms ||
    die "AnsibleForms service restart failed"
else
  pct exec "$VMID" -- bash /var/lib/tobe4home/install-ansibleforms-native.sh ||
    die "AnsibleForms installer failed; CT1001 kept for --resume"
  # Idempotent post-install invariant. This also catches regression if the
  # upstream installer alters its defaults in a later pinned release.
  pct exec "$VMID" -- python3 /var/lib/tobe4home/repair-ansibleforms-permissions.py --apply ||
    die "Native program permission validation refused after install"
fi
pct exec "$VMID" -- systemctl is-active --quiet mariadb ansibleforms ansibleforms-rte ||
  die "Native AnsibleForms services not all active; CT1001 kept"
echo "Checking AnsibleForms HTTPS localhost health (self-signed test only)..."
READY=0
for attempt in 1 2 3 4 5 6 7 8; do
  if pct exec "$VMID" -- curl -kfLsS --max-time 8 \
      -o /dev/null https://127.0.0.1/ >/dev/null 2>&1; then
    READY=1
    break
  fi
  [[ "$attempt" == 8 ]] || sleep 3
done
(( READY == 1 )) ||
  die "AnsibleForms HTTPS localhost healthcheck failed; inspect journal and --resume"
IP="$(pct exec "$VMID" -- ip -4 -o addr show dev eth0 |
  awk '{split($4,a,"/"); if(a[1]!=""){print a[1];exit}}')"
[[ -n "$IP" ]] || die "Cannot determine controller IPv4, login panel withheld"
[[ -t 0 && -t 1 ]] ||
  die "Login credentials are only shown in an attended terminal"
# LAST step: print a single compact login panel directly from the guarded
# guest-side app.env parser. Do not print any more task output after this.
# If the panel fails, --resume can safely revalidate and retry without
# generating or resetting any account or password.
pct exec "$VMID" -- python3 /var/lib/tobe4home/show-first-login.py --ip "$IP" ||
  die "First-login details unavailable; keep CT1001 and use --resume"

