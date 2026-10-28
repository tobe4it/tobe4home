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
       and /opt/ansibleforms/data/playbooks/tb4h-onboarding-preview.yml
Action: add the German beginner wizard and read-only overview playbook.
Existing form changes, examples, database, login, RTE and other Proxmox
guests will NOT be deleted or overwritten. Any conflicting filename blocks.
The web service is restarted to reload the form; it may disconnect sessions.
The web wizard is still PREVIEW ONLY, not a deployer.
PLAN
if [[ "$MODE" == preview ]]; then
  echo "PREVIEW ONLY – no changes. Run with --apply for confirmation."
  exit 0
fi
[[ -t 0 && -t 1 ]] || die "Apply requires an attended terminal"
read -r -p "Type ONBOARD 1001 to install ONLY this welcome form: " APPROVAL ||
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
pct push 1001 "$ROOT/ansibleforms/forms/tobe4home-start.yml" \
  /var/lib/tobe4home/tobe4home-start.yml --perms 0600
pct push 1001 "$ROOT/ansibleforms/playbooks/tb4h-onboarding-preview.yml" \
  /var/lib/tobe4home/tb4h-onboarding-preview.yml --perms 0600
pct exec 1001 -- python3 /var/lib/tobe4home/install-tobe4home-onboarding.py ||
  die "Welcome form not applied; other services and guests preserved"

pct exec 1001 -- systemctl restart ansibleforms ||
  die "AnsibleForms restart failed; examine journal, no reset needed"
pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte ||
  die "AnsibleForms did not return to active state"
pct exec 1001 -- curl -kfLsS --max-time 15 \
  -o /dev/null https://127.0.0.1/ ||
  die "HTTPS health failed; inspect service; do not delete CT1001"
IP="$(pct exec 1001 -- ip -4 -o addr show dev eth0 |
  awk '{split($4,a,"/");if(a[1]!=""){print a[1];exit}}')"
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
  die "Cannot determine guest IPv4"
printf '\nTOBE4HOME_ONBOARDING_READY=YES\n'
printf 'STARTSEITE=https://%s/form/tobe4home-start\n' "$IP"
printf 'STATUS=VORSCHAU; noch keine automatische Proxmox-Bereitstellung\n'
