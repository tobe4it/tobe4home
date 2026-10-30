#!/usr/bin/env bash
# CT1001-only, guarded NON-PROVISIONING Chat MVP retrofit.
# Read-only preview by default; never removes CT1001 or changes other guests.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
MODE=preview
if [[ $# -eq 1 && "$1" == "--apply" ]]; then
  MODE=apply
elif [[ $# -ne 0 ]]; then
  echo "Usage: sudo bash bootstrap/deploy-chat-mvp-1001.sh [--apply]" >&2
  exit 2
fi
die() { printf 'CHAT REFUSED: %s\n' "$*" >&2; exit 2; }
[[ "$EUID" == 0 ]] || die "Run as Proxmox host root"
for c in pct python3; do command -v "$c" >/dev/null || die "Missing $c"; done
for f in bootstrap/check-controller-config.py bootstrap/install-chat-mvp.py \
         chat/server.py chat/index.html chat/app.js chat/app.css; do
  [[ -f "$ROOT/$f" && -r "$ROOT/$f" ]] || die "Missing reviewed file $f"
done
CFG="$(pct config 1001)" || die "CT1001 not found"
python3 "$ROOT/bootstrap/check-controller-config.py" <<<"$CFG" ||
  die "CT1001 identity failed verification"
pct status 1001 | grep -Fxq "status: running" || die "CT1001 not running"
pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte ||
  die "Existing AnsibleForms/RTE services unhealthy"
pct exec 1001 -- test -d /var/lib/tobe4home || die "Missing controller staging directory"

cat <<'PLAN'
=== tobe4home CHAT MVP: ONLY CT1001 ===
Installs: /opt/tobe4home/chat/{server.py,index.html,app.js,app.css}
          /etc/tobe4home/chat.json (preserve locally edited settings)
          /etc/tobe4home/llm-api-key (empty, root-only by default)
          /etc/systemd/system/tb4h-chat.service
          local unprivileged account tb4h-chat (only if absent)
Starts:   ONE loopback-only Python chat server 127.0.0.1:8765
Connect:  HTTPS model API, or local-only HTTP. Not configured by default.
Access:   SSH tunnel to CT1001. NOT exposed on LAN or WAN.
NEVER:    provisions Proxmox guests, runs Ansible, writes generated playbooks,
          resets CT1001, modifies current AnsibleForms/database or other LXCs.
Existing local chat customizations or conflicting paths block installation.
PLAN

if [[ "$MODE" == preview ]]; then
  echo "PREVIEW_ONLY=YES -- nothing changed. Use --apply and approve CHAT 1001."
  exit 0
fi
[[ -t 0 && -t 1 ]] || die "Apply requires interactive SSH session"
read -r -p "Type CHAT 1001 to install ONLY this local preview service: " ANSWER || die "Approval cancelled"
[[ "$ANSWER" == "CHAT 1001" ]] || die "Approval mismatch"

CFG="$(pct config 1001)" || die "Controller disappeared"
python3 "$ROOT/bootstrap/check-controller-config.py" <<<"$CFG" ||
  die "Controller identity changed"
pct exec 1001 -- systemctl is-active --quiet ansibleforms ansibleforms-rte ||
  die "Controller services changed"
# Ensure no unrelated target already listens on our port.
if pct exec 1001 -- systemctl is-active --quiet tb4h-chat; then
  echo "Existing tobe4home chat service detected; installer will verify files."
else
  if pct exec 1001 -- bash -c 'ss -ltn "( sport = :8765 )" | grep -q LISTEN'; then
    die "Port 8765 is occupied by another service"
  fi
fi
if ! pct exec 1001 -- getent group tb4h-chat >/dev/null 2>&1; then
  pct exec 1001 -- groupadd --system tb4h-chat ||
    die "Cannot create isolated chat group"
fi
if ! pct exec 1001 -- id -u tb4h-chat >/dev/null 2>&1; then
  pct exec 1001 -- useradd --system --gid tb4h-chat --no-create-home --shell /sbin/nologin tb4h-chat ||
    die "Cannot create isolated chat account"
fi
UID_CHAT="$(pct exec 1001 -- id -u tb4h-chat)" || die "Chat account missing"
GID_CHAT="$(pct exec 1001 -- id -g tb4h-chat)" || die "Chat account missing"
GID_GROUP="$(pct exec 1001 -- getent group tb4h-chat | cut -d: -f3)" ||
  die "Chat group missing"
[[ "$UID_CHAT" =~ ^[0-9]+$ && "$UID_CHAT" != 0 &&
   "$GID_CHAT" == "$GID_GROUP" ]] ||
  die "Chat service user/group identity mismatch"
pct exec 1001 -- install -d -m 0700 /var/lib/tobe4home/chat-stage
for asset in server.py index.html app.js app.css; do
  pct push 1001 "$ROOT/chat/$asset" \
    "/var/lib/tobe4home/chat-stage/$asset" --perms 0600 ||
    die "Cannot stage $asset"
done
pct push 1001 "$ROOT/bootstrap/install-chat-mvp.py" \
  /var/lib/tobe4home/install-chat-mvp.py --perms 0700 ||
  die "Cannot stage chat installer"
pct exec 1001 -- python3 /var/lib/tobe4home/install-chat-mvp.py ||
  die "Chat install refused; no controller deletion"
pct exec 1001 -- systemctl is-active --quiet tb4h-chat ||
  die "Chat service did not start; review its journal"

STATE="$(pct exec 1001 -- curl -fsS --max-time 5 \
  -H 'Host: 127.0.0.1:8765' http://127.0.0.1:8765/api/status)" ||
  die "Chat loopback endpoint unhealthy"
python3 - "$STATE" <<'PY' || die "Unsafe/unexpected chat health response"
import json,sys
data=json.loads(sys.argv[1])
assert data.get("mode") == "READ_ONLY_PREVIEW"
assert data.get("configured") is False or data.get("configured") is True
assert isinstance(data.get("csrf"),str) and len(data["csrf"]) >= 20
print("TOBE4HOME_CHAT_LOOPBACK_HEALTH=YES")
PY
echo "TOBE4HOME_CHAT_RUNNING=YES"
echo "TOBE4HOME_CHAT_BIND=127.0.0.1:8765 (inside CT1001 ONLY)"
echo "TOBE4HOME_CHAT_MODEL=NOT_CONFIGURED_UNTIL_SITE_SETTINGS"
echo "TOBE4HOME_CHAT_PROXMOX_CHANGES=NONE"
echo "NEXT=Configure /etc/tobe4home/chat.json and SSH tunnel. See docs/CHAT-MVP.md"
