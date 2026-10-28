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
   -r "$ROOT/bootstrap/install-ansibleforms-native.sh" ]] ||
   die "Checkout incomplete"
if [[ "$MODE" != resume ]]; then
  echo "tobe4home – single Controller CT1001 (no CT1000)"
  if [[ -t 0 ]]; then
    [[ -n "$BRIDGE" ]] || BRIDGE="$(ask "Management bridge, e.g. vmbr3")"
    [[ -n "$STORAGE" ]] || STORAGE="$(ask "Rootfs storage, e.g. local-zfs")"
    [[ -n "$DNS" ]] || DNS="$(ask "Working IPv4 DNS server for guest")"
    if [[ -z "$KEY" ]]; then
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
  RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
    die "Cluster-wide inventory not available"
  python3 -c '
import json,sys
xs=json.load(sys.stdin)
assert isinstance(xs,list)
assert not any(int(x.get("vmid",-1))==1001 for x in xs if isinstance(x,dict))
' <<< "$RESOURCES" || die "VMID 1001 allocated"
  pct config "$VMID" >/dev/null 2>&1 && die "CT1001 already exists; use --resume"
  # Proxmox guest removal can leave an *empty* /var/lib/lxc/1001 directory.
  # The read-only preflight reports WARN in that case, and FAIL for nonempty
  # directories/symlinks. Only an empty directory may be removed with rmdir
  # after INSTALL 1001 approval, never rm -rf.
  if [[ -e /var/lib/lxc/1001 || -L /var/lib/lxc/1001 ]]; then
    [[ -d /var/lib/lxc/1001 && ! -L /var/lib/lxc/1001 ]] ||
      die "Unexpected CT1001 runtime path type"
    echo "NOTE: empty CT1001 runtime directory detected; will rmdir after approval."
  fi
  TEMPLATE_FILE="$(pveam available --section system |
    awk '$1=="system" && $2 ~ /^rockylinux-10-default_[0-9]+_amd64\.tar\.(xz|gz|zst)$/ {print $2}' |
    LC_ALL=C sort | tail -n 1)"
  [[ -n "$TEMPLATE_FILE" ]] || die "Official Rocky Linux 10 template missing in catalog"
  TEMPLATE="$TSTORE:vztmpl/$TEMPLATE_FILE"
  CACHED=no
  TPATH="$(pvesm path "$TEMPLATE" 2>/dev/null || true)"
  [[ -n "$TPATH" && -s "$TPATH" ]] && CACHED=yes
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
  # After INSTALL 1001 approval, only a completely empty directory may
  # be removed. rmdir never unlinks files or removes nonempty directories.
  if [[ -e /var/lib/lxc/1001 || -L /var/lib/lxc/1001 ]]; then
    [[ -d /var/lib/lxc/1001 && ! -L /var/lib/lxc/1001 ]] ||
      die "CT1001 leftover is not a normal directory"
    rmdir -- /var/lib/lxc/1001 ||
      die "CT1001 leftover not empty; inspect manually"
    echo "REMOVED ONLY EMPTY RUNTIME DIRECTORY: /var/lib/lxc/1001"
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
  grep -qx 'hostname: tb4h-controller' <<< "$CFG" || die "Unexpected CT1001 hostname"
  grep -qx 'unprivileged: 1' <<< "$CFG" || die "CT1001 not unprivileged"
  grep -Eq '^tags: .*tobe4home.*controller' <<< "$CFG" || die "Not the tobe4home controller"
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
pct exec "$VMID" -- bash /var/lib/tobe4home/install-ansibleforms-native.sh ||
  die "AnsibleForms installer failed; CT1001 kept for --resume"
pct exec "$VMID" -- systemctl is-active ansibleforms ansibleforms-rte ||
  die "AnsibleForms systemd check failed; CT1001 kept"
IP="$(pct exec "$VMID" -- ip -4 -o addr show dev eth0 |
  awk '{split($4,a,"/"); if(a[1]!=""){print a[1];exit}}')"
echo "SINGLE-CONTROLLER CT1001 READY: https://$IP/"
echo "Login: admin; password printed by upstream installer above."
echo "No Proxmox credentials and no infrastructure guests have been deployed."
