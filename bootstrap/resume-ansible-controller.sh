#!/usr/bin/env bash
# Resume ONLY the existing unprivileged CT 1001. No create or deletion.
set -Eeuo pipefail
umask 077
VMID=1001
APPLY=0
DNS_OVERRIDE=""
BRIDGE=""
fail() { printf 'STOP: %s\n' "$*" >&2; exit 2; }

for arg in "$@"; do
  case "$arg" in
    --bridge=*) BRIDGE="\${arg#*=}" ;;
    --nameserver=*) DNS_OVERRIDE="\${arg#*=}" ;;
    --apply) APPLY=1 ;;
    *) fail "Usage: $0 --bridge=vmbrN [--nameserver=DNS-IP] [--apply]" ;;
  esac
done

[[ "$EUID" -eq 0 ]] || fail "Run on Proxmox as root"
[[ "$BRIDGE" =~ ^vmbr[0-9]+$ ]] || fail "Specify the CT bridge"
for command_name in pct python3 timeout; do
  command -v "$command_name" >/dev/null || fail "Missing $command_name"
done

# Fail closed if VMID belongs to a different container.
CT_CONFIG="$(pct config "$VMID")" || fail "CT 1001 missing: no resume"
grep -qx 'hostname: tb4h-ansible' <<< "$CT_CONFIG" ||
  fail "CT 1001 is not tb4h-ansible"
grep -qx 'unprivileged: 1' <<< "$CT_CONFIG" ||
  fail "CT 1001 is not unprivileged"
grep -Eq "^net0: .*bridge=\${BRIDGE}(,|$)" <<< "$CT_CONFIG" ||
  fail "CT 1001 is not attached to the selected bridge"
grep -Eq '^rootfs: [^[:space:]]+' <<< "$CT_CONFIG" ||
  fail "CT root filesystem not configured"
[[ "$(pct status "$VMID")" == "status: running" ]] ||
  fail "Guest not running. Inspect before resuming."

# Reuse the Stage-0 site-local DNS setting, not the host DNS by assumption.
if [[ -n "$DNS_OVERRIDE" ]]; then
  DNS="$DNS_OVERRIDE"
  DNS_ORIGIN="explicit operator selection"
else
  DNS="$(pct exec 1000 -- python3 -c '
import ipaddress, json
from pathlib import Path
obj = json.loads(Path("/var/lib/tobe4home/site.local.json").read_text())
value = obj.get("dns_resolver", "")
addr = ipaddress.ip_address(value)
if addr.version != 4 or addr.is_loopback or addr.is_multicast or addr.is_unspecified:
    raise SystemExit(2)
print(addr)
' 2>/dev/null)" ||
    fail "No usable saved DNS from CT 1000: supply --nameserver=IP"
  DNS_ORIGIN="Stage-0 saved site settings"
fi
python3 - "$DNS" <<'PY' || fail "Invalid selected DNS IP"
import ipaddress, sys
try:
    ip = ipaddress.ip_address(sys.argv[1])
    if ip.version != 4 or ip.is_loopback or ip.is_multicast:
        raise ValueError("Unsupported DNS")
    if ip.is_unspecified or ip.is_link_local:
        raise ValueError("Unroutable DNS")
except ValueError:
    raise SystemExit(2)
PY

echo "=== TOBE4HOME STAGE-1 RESUME ==="
echo "Existing guest: CT 1001 tb4h-ansible; unprivileged; bridge: $BRIDGE"
echo "Resolver proposal: $DNS ($DNS_ORIGIN)"
echo "PVE nameserver: $(grep '^nameserver: ' <<< "$CT_CONFIG" || echo '<host-inherited>')"
echo "Effective guest /etc/resolv.conf:"
pct exec "$VMID" -- cat /etc/resolv.conf
echo "Guest IPv4 routes:"
pct exec "$VMID" -- ip -4 route || true

DNS_OK=0
if timeout 12 pct exec "$VMID" -- getent ahostsv4 mirrors.rockylinux.org >/dev/null 2>&1; then
  DNS_OK=1
  echo "DNS lookup: PASS; resolver setting will remain unchanged."
else
  echo "DNS lookup: FAIL. Proposed fix: set nameserver on CT 1001 and reboot only CT 1001."
fi
echo "Next: resume ansible-core, git, SSH package installation; verify local Ansible."
echo "No CT creation, no changes to CT 1000, no resource deletion."

if (( ! APPLY )); then
  echo "READ-ONLY: no changes made. Review before --apply."
  exit 0
fi
read -r -p "Type RESUME 1001 to approve: " CONFIRM
[[ "$CONFIRM" == "RESUME 1001" ]] || fail "Cancelled without changes"

if (( ! DNS_OK )); then
  pct set "$VMID" --nameserver "$DNS"
  echo "PVE nameserver configured. Rebooting only CT 1001..."
  pct reboot "$VMID"
  for _ in $(seq 1 30); do
    if pct status "$VMID" | grep -qx 'status: running' &&
       pct exec "$VMID" -- true 2>/dev/null; then
      break
    fi
    sleep 2
  done
  [[ "$(pct status "$VMID")" == "status: running" ]] ||
    fail "Guest did not return to running state"
fi
timeout 15 pct exec "$VMID" -- getent ahostsv4 mirrors.rockylinux.org >/dev/null ||
  fail "DNS still unavailable; stop before DNF"
pct exec "$VMID" -- dnf -y install ansible-core git openssh-clients openssh-server python3 iproute
pct exec "$VMID" -- systemctl enable --now sshd
pct exec "$VMID" -- ansible --version
pct exec "$VMID" -- ansible localhost -c local -m ansible.builtin.ping
echo "STAGE-1 ANSIBLE CONTROLLER READY: CT 1001"
echo "Guest has no privileged deployment credentials yet."
