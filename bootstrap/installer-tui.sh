#!/usr/bin/env bash
# Debian-installer-style stage-0 TUI. Runs on Proxmox; no packages installed.
# whiptail uses the existing host terminal; never needs a guest to show dialogs.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP="$ROOT/bootstrap/bootstrap.sh"
NETWORKS="$ROOT/bootstrap/networks.py"
BACKTITLE="tobe4home | Proxmox Bootstrap (Entwicklungsversion)"

fail() { printf 'FEHLER: %s\n' "$*" >&2; exit 1; }
cancel() { printf 'Einrichtung abgebrochen. Keine Installation gestartet.\n'; exit 0; }
msg() {
  whiptail --backtitle "$BACKTITLE" --title "$1" --msgbox "$2" 15 78
}
question() {
  whiptail --backtitle "$BACKTITLE" --title "$1" --defaultno --yesno "$2" 15 78
}
input() {
  local title="$1" prompt="$2" proposal="$3"
  whiptail --backtitle "$BACKTITLE" --title "$title" \
    --inputbox "$prompt" 15 78 "$proposal" 3>&1 1>&2 2>&3
}
menu() {
  local title="$1" prompt="$2"; shift 2
  whiptail --backtitle "$BACKTITLE" --title "$title" \
    --menu "$prompt" 22 88 13 "$@" 3>&1 1>&2 2>&3
}

[[ $EUID -eq 0 ]] || fail "Als root auf dem Proxmox-Host ausführen."
[[ -t 0 && -t 1 ]] || fail "Eine interaktive Konsole ist notwendig."
command -v whiptail >/dev/null || fail "whiptail fehlt. Den Textmodus mit TOBE4HOME_INSTALLER_UI=text nutzen."
[[ -r "$BOOTSTRAP" && -r "$NETWORKS" ]] || fail "Unvollständiger Bootstrap-Checkout."
for cmd in git pct pvesh pvesm pveam python3; do
  command -v "$cmd" >/dev/null || fail "Notwendiger Befehl fehlt: $cmd"
done
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
  fail "Git-Dateien lokal verändert; Installation erst nach Prüfung."
fi

REVISION="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
question "Willkommen" "tobe4home | Erstinstallation auf Proxmox VE

Quellstand: $REVISION

Diese Entwicklungsfassung richtet EINEN neuen, unprivilegierten
Rocky-Linux-10-Container mit lokaler Setup-WebApp ein.

Zunächst werden ausschließlich Einstellungen ermittelt.
Vor dem Download oder einer Änderung erfolgt eine eigene Freigabe.

Einrichtung beginnen?" || cancel

RESOURCES="$(pvesh get /cluster/resources --type vm --output-format json)" ||
  fail "Proxmox-Clusterinventar nicht lesbar."
SUGGESTED_ID="$(python3 -c '
import json,sys
used = {int(x["vmid"]) for x in json.load(sys.stdin) if "vmid" in x}
print(next((i for i in range(1000, 2000) if i not in used), ""))
' <<< "$RESOURCES")" || fail "Proxmox-Clusterinventar ungültig."
[[ -n "$SUGGESTED_ID" ]] || fail "Der bevorzugte VMID-Bereich 1000–1999 ist belegt."

# Each invalid answer stays on its screen rather than terminating the setup.
while true; do
  VMID="$(input "Schritt 1/5 – Container-Nummer" \
    "Vorgeschlagen wird die erste freie VMID im Bereich 1000–1999.
Die Nummer kann überschrieben werden." "$SUGGESTED_ID")" || cancel
  if [[ ! "$VMID" =~ ^[1-9][0-9]{2,8}$ ]]; then
    msg "Ungültige VMID" "Bitte eine gültige Proxmox-VMID eingeben."
    continue
  fi
  if python3 -c '
import json,sys
vmid = int(sys.argv[1])
sys.exit(0 if any(int(x.get("vmid",-1)) == vmid for x in json.load(sys.stdin)) else 1)
' "$VMID" <<< "$RESOURCES"; then
    msg "VMID bereits belegt" "Container-/VM-ID $VMID existiert bereits. Bitte eine andere wählen."
    continue
  fi
  break
done

while true; do
  RAW_PREFIX="$(input "Schritt 2/5 – Namenspräfix" \
    "Vorschlag: tobe4home-
Der erste Container erhält den Namen PRAEFIX-setup.

Erlaubt sind Kleinbuchstaben, Ziffern und Bindestriche.
Ein Unterstrich (_) ist in Hostnamen nicht zulässig." "tobe4home-")" || cancel
  PREFIX="${RAW_PREFIX%-}"
  if [[ "$PREFIX" =~ ^[a-z]([a-z0-9-]*[a-z0-9])?$ ]] &&
     (( ${#PREFIX} <= 57 )); then
    break
  fi
  SUGGESTED_PREFIX="${RAW_PREFIX//_/-}"
  SUGGESTED_PREFIX="${SUGGESTED_PREFIX%-}"
  if [[ "$RAW_PREFIX" == *"_"* &&
        "$SUGGESTED_PREFIX" =~ ^[a-z]([a-z0-9-]*[a-z0-9])?$ ]] &&
     (( ${#SUGGESTED_PREFIX} <= 57 )); then
    if question "Präfix korrigieren" \
       "'$RAW_PREFIX' enthält einen ungültigen Unterstrich.

Soll stattdessen '${SUGGESTED_PREFIX}-' verwendet werden?
Der Container heißt dann '${SUGGESTED_PREFIX}-setup'."; then
      PREFIX="$SUGGESTED_PREFIX"
      break
    fi
  fi
  msg "Ungültiger Präfix" \
    "Der Namenspräfix muss ein gültiges DNS-Label sein:
Kleinbuchstaben, Ziffern und interne Bindestriche,
höchstens 57 Zeichen. Bitte erneut eingeben."
done

# "pvesm status --content rootdir" is the documented supported filter.
# A dedicated parser validates its table shape and selects only active stores.
STORAGE_JSON="$(python3 "$ROOT/bootstrap/storages.py" --json)" ||
  fail "Keine aktiven LXC-RootFS-Storages erkannt."
STORAGE_ITEMS=()
while IFS='|' read -r NAME TYPE; do
  [[ -n "$NAME" ]] || continue
  STORAGE_ITEMS+=("$NAME" "Aktiv | $TYPE | LXC-RootFS")
done < <(python3 -c '
import json,sys
for item in json.load(sys.stdin):
    print(item["name"] + "|" + item["type"])
' <<< "$STORAGE_JSON")
(( ${#STORAGE_ITEMS[@]} > 0 )) ||
  fail "Kein aktiver Storage für LXC-RootFS ermittelt."
STORAGE="$(menu "Schritt 3/5 – Datenspeicher" \
  "Wähle den Speicherort für die Systemplatte des Setup-Containers.
Vorhandene Volumes werden nicht verändert." "${STORAGE_ITEMS[@]}")" || cancel

NETWORK_JSON="$(python3 "$NETWORKS" --json)" ||
  fail "Brücken konnten nicht eingelesen werden."
NETWORK_LINES="$(python3 -c '
import json,sys
for b in json.load(sys.stdin):
    name=b["name"]
    state="UP" if b["up"] else "DOWN"
    vlan="VLAN-aware" if b["vlan_aware"] else "untagged only"
    default="Host-Default-Route" if b["host_default_route"] else "keine Host-Default-Route"
    print("|".join((name,str(int(b["vlan_aware"])),state,vlan,default)))
' <<< "$NETWORK_JSON")" || fail "Fehler bei der Bridge-Aufbereitung."

BRIDGE_ITEMS=()
declare -A BRIDGE_AWARE
while IFS='|' read -r NAME AWARE STATE VLAN_MODE ROUTE; do
  [[ -n "$NAME" ]] || continue
  BRIDGE_AWARE["$NAME"]="$AWARE"
  BRIDGE_ITEMS+=("$NAME" "$STATE | $VLAN_MODE | $ROUTE")
done <<< "$NETWORK_LINES"
(( ${#BRIDGE_ITEMS[@]} > 0 )) || fail "Keine VM-Brücke gefunden."
while true; do
  BRIDGE="$(menu "Schritt 4/5 – Bridge" \
    "Wähle die Bridge des INTERNEN Netzes, von dem aus dein
Administrationsgerät den Setup-Gast erreichen kann.
Bridge-Namen sind keine Netzwerkrollen; keine automatische Zuordnung." \
    "${BRIDGE_ITEMS[@]}")" || cancel
  if ! python3 "$NETWORKS" --validate "$BRIDGE" >/dev/null 2>&1; then
    msg "Netzwerk nicht nutzbar" "Diese Bridge ist nicht aktiv. Bitte eine aktive Bridge auswählen."
    continue
  fi
  break
done

VLAN=""
if [[ "${BRIDGE_AWARE[$BRIDGE]}" == "1" ]]; then
  while true; do
    VLAN="$(input "Schritt 4/5 – VLAN" \
      "Die Bridge $BRIDGE ist VLAN-aware.

Optional: VLAN-ID 1 bis 4094.
Leer lassen für ein ungetaggtes Netzwerk.

Die Bridge-Nummer ist nicht die VLAN-ID!" "")" || cancel
    [[ -z "$VLAN" ]] && break
    if [[ "$VLAN" =~ ^[1-9][0-9]{0,3}$ ]] &&
       (( 10#$VLAN >= 1 && 10#$VLAN <= 4094 )); then
      python3 "$NETWORKS" --validate "$BRIDGE" --tag "$VLAN" >/dev/null ||
        fail "Bridge/VLAN-Auswahl nicht gültig."
      break
    fi
    msg "Ungültiger VLAN-Tag" "VLAN-ID 1 bis 4094 eingeben, oder leer für ungetaggt."
  done
else
  msg "VLAN" "$BRIDGE ist nicht VLAN-aware; es wird ungetaggt angeschlossen."
fi

# Authorized login keys can be read without touching host private keys.
# Copy precisely the selected public key into an owner-only /run staging file,
# and remove it on every exit (including cancellation and failed preflight).
KEY_HELPER="$ROOT/bootstrap/ssh_keys.py"
[[ -r "$KEY_HELPER" ]] || fail "SSH-Key-Erkennung fehlt im Bootstrap-Checkout."
KEY_TEMP_DIR="$(mktemp -d /run/tobe4home-ssh.XXXXXXXX)" ||
  fail "Temporäres SSH-Verzeichnis kann nicht angelegt werden."
chmod 0700 "$KEY_TEMP_DIR"
trap 'rm -rf -- "$KEY_TEMP_DIR"' EXIT
KEY="$KEY_TEMP_DIR/admin.pub"

while true; do
  KEY_CANDIDATES="$(python3 "$KEY_HELPER" --list)" ||
    fail "SSH-Anmeldeschlüssel können nicht ausgelesen werden."
  KEY_ITEMS=()
  declare -A KEY_FPS=()
  declare -A KEY_SOURCES=()
  while IFS='|' read -r KEY_IDX KEY_SOURCE KEY_ALG KEY_FP; do
    [[ -n "$KEY_IDX" ]] || continue
    KEY_ITEMS+=("$KEY_IDX" "$KEY_SOURCE | $KEY_ALG | $KEY_FP")
    KEY_FPS["$KEY_IDX"]="$KEY_FP"
    KEY_SOURCES["$KEY_IDX"]="$KEY_SOURCE"
  done < <(python3 -c '
import json,sys
for x in json.load(sys.stdin):
    print("|".join([x["index"],x["source"],x["algorithm"],x["fingerprint"]]))
' <<< "$KEY_CANDIDATES")
  KEY_ITEMS+=("paste" "Eigenen PUBLIC Key aus Termius einfügen")
  KEY_ITEMS+=("file" "Vorhandenen öffentlichen Schlüssel per Pfad wählen")
  KEY_CHOICE="$(menu "Schritt 5/5 – SSH-Schlüssel" \
    "Erkannte SSH-Login-Schlüssel des Administrators.

Ein passender öffentlicher Login-Schlüssel kann für den
neuen Gast wiederverwendet werden – ohne manuelle Datei-
anlage und ohne Kopieren irgendeines privaten Schlüssels.

Prüfe, dass dein Administrationsgerät den privaten
Gegenpart besitzt. Wähle den Schlüssel oder Import." \
    "${KEY_ITEMS[@]}")" || cancel

  if [[ "$KEY_CHOICE" == paste ]]; then
    PUBLIC_KEY="$(input "SSH Public Key einfügen" \
      "Den ÖFFENTLICHEN SSH-Key aus Termius einfügen
(ssh-ed25519 / ecdsa / ssh-rsa).
Nie den privaten Schlüssel übertragen." "")" || cancel
    if KEY_FP="$(python3 "$KEY_HELPER" --from-stdin \
      --destination "$KEY" <<< "$PUBLIC_KEY" 2>/dev/null)"; then
      msg "Schlüssel übernommen" "Public Key validiert. Fingerprint:
$KEY_FP

Nur der öffentliche Schlüssel wird an den neuen LXC gegeben."
      break
    fi
    msg "Kein gültiger Public Key" \
      "Bitte eine einzelne gültige SSH-Public-Key-Zeile einfügen."
  elif [[ "$KEY_CHOICE" == file ]]; then
    KEY_SOURCE_FILE="$(input "SSH Public-Key-Datei" \
      "Pfad zu einer vorhandenen PUBLIC-Key-Datei
auf dem Proxmox-Host (niemals privaten Schlüssel)." "")" || cancel
    if [[ -f "$KEY_SOURCE_FILE" && -r "$KEY_SOURCE_FILE" ]] &&
       KEY_FP="$(python3 "$KEY_HELPER" --from-stdin \
         --destination "$KEY" < "$KEY_SOURCE_FILE" 2>/dev/null)"; then
      msg "Schlüssel übernommen" "Public Key validiert. Fingerprint:
$KEY_FP"
      break
    fi
    msg "Ungültige Datei" "Kein einzelner gültiger Public Key in dieser Datei."
  elif [[ -n "${KEY_FPS[$KEY_CHOICE]:-}" ]]; then
    CHOSEN_FP="${KEY_FPS[$KEY_CHOICE]}"
    CHOSEN_SOURCE="${KEY_SOURCES[$KEY_CHOICE]}"
    if ! question "SSH-Schlüssel bestätigen" \
      "Anmeldeschlüssel aus:
$CHOSEN_SOURCE

Fingerprint:
$CHOSEN_FP

Hat dein Administrationsgerät (z. B. Termius) den
dazugehörigen privaten Schlüssel?

Nur der öffentliche Schlüssel wird kopiert."; then
      continue
    fi
    if KEY_FP="$(python3 "$KEY_HELPER" --export "$CHOSEN_FP" \
      --destination "$KEY" 2>/dev/null)"; then
      break
    fi
    msg "Schlüssel geändert" \
      "Der gewählte SSH-Schlüssel ist nicht mehr verfügbar.
Bitte erneut auswählen."
  else
    msg "Ungültige Auswahl" "Bitte einen angezeigten Schlüssel auswählen."
  fi
done

ARGS=(--vmid "$VMID" --storage "$STORAGE" --container-prefix "$PREFIX" \
  --bridge "$BRIDGE" --ssh-public-key "$KEY")
[[ -z "$VLAN" ]] || ARGS+=(--vlan-tag "$VLAN")
VLAN_LABEL="${VLAN:-ungetaggt}"

question "Installationsübersicht" "Es ist noch nichts installiert.

VMID:           $VMID
Hostname:       ${PREFIX}-setup
Betriebssystem: Rocky Linux 10
RootFS:         $STORAGE
Bridge:         $BRIDGE
VLAN:           $VLAN_LABEL
WebApp:         nur über SSH-Tunnel
SSH-Fingerprint: $KEY_FP (aus SSH-Login oder Import)

Template wird bei Bedarf von Proxmox heruntergeladen.

Diese Angaben unverändert prüfen?" || cancel

PREVIEW="$(bash "$BOOTSTRAP" "${ARGS[@]}" 2>&1)" || {
  msg "Vorprüfung fehlgeschlagen" "Die read-only Vorprüfung ist fehlgeschlagen:

$PREVIEW

Es wurde kein Container installiert."
  exit 1
}
whiptail --backtitle "$BACKTITLE" --title "Vorprüfung erfolgreich" \
  --scrolltext --msgbox "$PREVIEW

WICHTIG: Read-only-Prüfungen können einen neuen ZFS-Subvolume-
Mount oder seine UID/GID-Zuordnung noch nicht vollständig testen.
Netzwerkkonfiguration und Paketquellen werden erst im Gast geprüft.

Der nächste Schritt erstellt genau EINEN LXC.
Noch ist keine Installation erfolgt." 24 96

APPROVAL="$(input "Verbindliche Freigabe" \
  "ENTWICKLUNGSVERSION – bisher kein vollständiger Proxmox-Realtest.

Für die tatsächliche LXC-Erstellung einschließlich
Rocky-Download und dnf-Installation gib exakt ein:

INSTALL $VMID

Abbrechen lässt die gesamte Installation unverändert." "")" || cancel
if [[ "$APPROVAL" != "INSTALL $VMID" ]]; then
  msg "Abgebrochen" "Keine Installation freigegeben. Es wurden keine Gäste angelegt."
  exit 0
fi

# From here on, this is the explicitly approved write phase.
printf '\n=== tobe4home: bestätigte Stage-0-Installation (VMID %s) ===\n' "$VMID"
bash "$BOOTSTRAP" "${ARGS[@]}" --apply
# Only reached after the core bootstrap verified its HTTP health endpoint.
GUEST_ADDRESS="$(pct exec "$VMID" -- ip -4 -o addr show dev eth0 2>/dev/null |
  awk '{split($4,a,"/"); if(a[1] != "") {print a[1]; exit}}')"
PVE_LOGIN="${SUDO_USER:-root}"
whiptail --backtitle "$BACKTITLE" --title "tobe4home – Setup bereit" \
  --scrolltext --msgbox "CT $VMID (${PREFIX}-setup) ist eingerichtet.
Die lokale WebApp hat ihren HTTP-Healthcheck bestanden.

WEBADRESSE (auf deinem Rechner NACH Einrichtung des SSH-Tunnels):
http://127.0.0.1:8765/

Gast-IP: $GUEST_ADDRESS

Tunnel vom Administrationsgerät:
ssh -N -J $PVE_LOGIN@<PROXMOX-ADRESSE> \
  -L 8765:127.0.0.1:8765 tobe4home@$GUEST_ADDRESS

Diese Adresse ist nicht direkt aus dem LAN erreichbar.
Ein SSH-Tunnel ist wegen der noch fehlenden Authentifizierung nötig." 23 95
