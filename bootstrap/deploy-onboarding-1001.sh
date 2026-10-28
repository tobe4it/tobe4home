#!/usr/bin/env bash
# Controlled UI-only retrofit for the EXISTING tb4h-controller CT1001.
# No reset, new CTs, Proxmox API credentials or AnsibleForms reinstall.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODE=preview
[[ $# == 0 ]] || { [[ $# == 1 && "$1" == "--apply" ]] && MODE=apply || {
  echo "Usage: sudo bash bootstrap/deploy-onboarding-1001.sh [--apply]" >&2; exit 2;
}; }
die() { echo "STOP: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || die "Proxmox host root required"
for c in pct python3; do command -v "$c" >/dev/null || die "Missing $c"; done
for p in bootstrap/check-controller-config.py \
         bootstrap/install-tobe4home-onboarding.py \
         bootstrap/collect-proxmox-inventory.py \
         bootstrap/install-proxmox-snapshot.py \
         ansibleforms/forms/tobe4home-start.yml \
         ansibleforms/playbooks/tb4h-onboarding-preview.yml; do
  [[ -r "$ROOT/$p" ]] || die "Missing checked-out asset $p"
done
CFG="$(pct config 1001)" || die "CT1001 does not exist"
python3 "$ROOT/bootstrap/check-controller-config.py" <<< "$CFG" ||
  die "Existing guest is not verified tobe4home CT1001"
pct status 1001 | grep -Fxq "status: running" || die "Controller is not running"
pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte ||
  die "Native AnsibleForms/RTE must already be active (not reinstalling)"

cat <<'PLAN'
=== TOBE4HOME STARTSEITE – CT1001 ===
Scope: ONLY /opt/ansibleforms/data/forms/tobe4home-start.yml
       /opt/ansibleforms/data/playbooks/tb4h-onboarding-preview.yml
       /opt/ansibleforms/data/playbooks/tb4h-proxmox-snapshot.json
Action: update the German beginner wizard and snapshot guest counts
        read-only on the PVE HOST (pct list, qm list) when approved.
Existing form changes, examples, database, login, RTE and other Proxmox
guests will NOT be deleted or overwritten. Any conflicting filename blocks.
The web service is restarted to reload the form; it may disconnect sessions.
The web wizard is still PREVIEW ONLY, not a deployer.
This is a point-in-time PVE guest inventory, not a scan of services.
PLAN
if [[ "$MODE" == preview ]]; then
  echo "PREVIEW ONLY – no changes. Run with --apply for confirmation."
  exit 0
fi
[[ -t 0 && -t 1 ]] || die "Apply requires an attended terminal"
read -r -p "Type ONBOARD 1001 to install only this onboarding and inventory snapshot: " APPROVAL ||
  die "Input cancelled"
[[ "$APPROVAL" == "ONBOARD 1001" ]] || die "Cancelled"

# Re-verify exact guest identity before any write.
CFG="$(pct config 1001)" || die "Controller vanished"
python3 "$ROOT/bootstrap/check-controller-config.py" <<< "$CFG" ||
  die "Controller identity changed"
pct exec 1001 -- test -d /var/lib/tobe4home ||
  die "Missing controller-local staging directory"
pct exec 1001 -- test -f /etc/systemd/system/ansibleforms.service ||
  die "Not the native AnsibleForms service"

pct push 1001 "$ROOT/bootstrap/install-tobe4home-onboarding.py" \
  /var/lib/tobe4home/install-tobe4home-onboarding.py --perms 0700
pct push 1001 "$ROOT/bootstrap/install-proxmox-snapshot.py" \
  /var/lib/tobe4home/install-proxmox-snapshot.py --perms 0700
pct push 1001 "$ROOT/ansibleforms/forms/tobe4home-start.yml" \
  /var/lib/tobe4home/tobe4home-start.yml --perms 0600
pct push 1001 "$ROOT/ansibleforms/playbooks/tb4h-onboarding-preview.yml" \
  /var/lib/tobe4home/tb4h-onboarding-preview.yml --perms 0600
# PVE host only: never grant AnsibleForms access to Proxmox or scan other
# guests. Exclude the controller; publish only anonymized guest counts.
TB4H_INV_FILE="$(mktemp /tmp/tb4h-inventory.XXXXXXXX)" ||
  die "Cannot allocate private host inventory staging file"
trap 'rm -f -- "${TB4H_INV_FILE:-/dev/null}"' EXIT
python3 "$ROOT/bootstrap/collect-proxmox-inventory.py" > "$TB4H_INV_FILE" ||
  die "Read-only Proxmox inventory failed; no guest modifications"
pct push 1001 "$TB4H_INV_FILE" \
  /var/lib/tobe4home/tb4h-proxmox-snapshot.json --perms 0600 ||
  die "Cannot stage host inventory"
pct exec 1001 -- python3 /var/lib/tobe4home/install-proxmox-snapshot.py ||
  die "Snapshot verification failed; no guest reset"
pct exec 1001 -- python3 /var/lib/tobe4home/install-tobe4home-onboarding.py ||
  die "Welcome form not applied; other services and guests preserved"

pct exec 1001 -- systemctl restart ansibleforms ||
  die "AnsibleForms restart failed; examine journal, no reset needed"
READY=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte &&
     pct exec 1001 -- curl -kfLsS --max-time 8 \
       -o /dev/null https://127.0.0.1/ >/dev/null 2>&1; then
    READY=1
    break
  fi
  [[ "$attempt" == 10 ]] || sleep 3
done
(( READY == 1 )) ||
  die "HTTPS or native services unhealthy after UI restart; no CT reset performed"
IP="$(pct exec 1001 -- ip -4 -o addr show dev eth0 |
  awk '{split($4,a,"/");if(a[1]!=""){print a[1];exit}}')"
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
  die "Cannot determine guest IPv4"
printf '\nTOBE4HOME_ONBOARDING_READY=YES\n'
printf 'STARTSEITE=https://%s/form/tobe4home-start\n' "$IP"
printf 'STATUS=VORSCHAU; noch keine automatische Proxmox-Bereitstellung\n'
