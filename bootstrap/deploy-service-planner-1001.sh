#!/usr/bin/env bash
# Controlled retrofit of a NON-EXECUTING service planning form to CT1001.
# Existing Proxmox guests, AnsibleForms accounts and RTE are preserved.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODE=preview
if [[ "$#" -eq 1 && "$1" == "--apply" ]]; then
  MODE=apply
elif [[ "$#" -ne 0 ]]; then
  echo "Usage: sudo bash bootstrap/deploy-service-planner-1001.sh [--apply]" >&2
  exit 2
fi
die() { echo "STOP: $*" >&2; exit 2; }
[[ "$EUID" -eq 0 ]] || die "Proxmox host root required"
for cmd in pct python3; do
  command -v "$cmd" >/dev/null || die "Missing $cmd"
done
for asset in \
  bootstrap/check-controller-config.py \
  bootstrap/install-tobe4home-planner.py \
  ansibleforms/forms/tobe4home-service-plan.yml \
  ansibleforms/playbooks/tb4h-service-plan-preview.yml; do
  [[ -f "$ROOT/$asset" && -r "$ROOT/$asset" ]] || die "Missing reviewed asset: $asset"
done

CFG="$(pct config 1001)" || die "CT1001 does not exist"
python3 "$ROOT/bootstrap/check-controller-config.py" <<< "$CFG" ||
  die "Identity or configuration of CT1001 is not verified"
pct status 1001 | grep -Fxq "status: running" || die "CT1001 is not running"
pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte ||
  die "Existing AnsibleForms and RTE must already be healthy"
pct exec 1001 -- test -f /opt/ansibleforms/data/playbooks/tb4h-proxmox-snapshot.json ||
  die "Read-only inventory missing; complete onboarding first"
pct exec 1001 -- test -d /var/lib/tobe4home ||
  die "Controller staging directory missing"

cat <<'PREVIEW'
=== tobe4home – NEUER DIENSTPLANER (nur CT1001) ===
Geplant: ein neues deutschsprachiges Formular für Freitext-Dienstaufträge
         und ein ausschließlich lokales, nicht ausführendes RTE-Playbook.
Dienstprofile: Paperless, DNS-Filter, Proxy, Mailserver.
Die vorhandene anonymisierte Proxmox-Momentaufnahme wird nur gelesen.
NICHT enthalten: LLM-Backend, Chat-Verlauf, produktives Ansible,
                 Git-Branch-Erzeugung, OpenTofu und Provisionierung.
Geschützt: bestehende Gäste, andere Formulare, MariaDB, Admin-Zugang,
           Proxmox-Credentials, individuelle Änderungen an Zieldateien.
Nur die AnsibleForms-WebApp wird für das Einlesen neu gestartet.
PREVIEW
if [[ "$MODE" == "preview" ]]; then
  echo "PREVIEW_ONLY=YES – keine Änderungen. --apply verlangt Freigabe."
  exit 0
fi

[[ -t 0 && -t 1 ]] || die "An interactive terminal is required"
read -r -p "Type PLAN 1001 to install the non-executing planning form: " APPROVAL ||
  die "Confirmation cancelled"
[[ "$APPROVAL" == "PLAN 1001" ]] || die "Cancelled"

# Re-read host-side identity and guest health immediately before writing.
CFG="$(pct config 1001)" || die "CT1001 vanished"
python3 "$ROOT/bootstrap/check-controller-config.py" <<< "$CFG" ||
  die "CT1001 identity changed"
pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte ||
  die "Controller became unhealthy"
pct push 1001 "$ROOT/bootstrap/install-tobe4home-planner.py" \
  /var/lib/tobe4home/install-tobe4home-planner.py --perms 0700
pct push 1001 "$ROOT/ansibleforms/forms/tobe4home-service-plan.yml" \
  /var/lib/tobe4home/tobe4home-service-plan.yml --perms 0600
pct push 1001 "$ROOT/ansibleforms/playbooks/tb4h-service-plan-preview.yml" \
  /var/lib/tobe4home/tb4h-service-plan-preview.yml --perms 0600
pct exec 1001 -- python3 /var/lib/tobe4home/install-tobe4home-planner.py ||
  die "Planner assets refused; no existing form replaced"
pct exec 1001 -- systemctl restart ansibleforms ||
  die "AnsibleForms web reload failed; CT1001 preserved"
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
  die "Controller HTTPS or RTE unhealthy; do not reinstall CT1001"
IP="$(pct exec 1001 -- ip -4 -o addr show dev eth0 |
  awk '{split($4,a,"/");if(a[1]!=""){print a[1];exit}}')"
[[ "$IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
  die "Cannot determine CT1001 IPv4"
echo "TOBE4HOME_PLANNER_READY=YES"
printf 'PLANER=https://%s/form/tobe4home-dienstplanung\n' "$IP"
echo "MODE=PREVIEW_ONLY"
echo "LLM_CONNECTED=NO"
echo "PROXMOX_CHANGES=0"
