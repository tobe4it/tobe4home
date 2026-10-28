#!/usr/bin/env bash
# Destroy ONLY the explicitly identified disposable tobe4home controller CT1001.
# Never deletes backups, foreign guests, unreferenced volumes or runtime trees.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
VMID=1001
MODE=preview
die() { printf 'RESET REFUSED: %s\n' "$*" >&2; exit 2; }

usage() {
  cat <<'HELP'
tobe4home CT1001 clean reset (Proxmox host only)
  sudo bash bootstrap/reset-controller.sh            # READ-ONLY preview
  sudo bash bootstrap/reset-controller.sh --destroy  # typed DELETE 1001 approval

Scope: only an existing CT1001 with hostname=tb4h-controller,
unprivileged=1, rootfs=subvol-1001-disk-N and both tobe4home/controller tags.
No recursive rm, no --destroy-unreferenced-disks, no modification of CT1000.
Does not delete external vzdump / PBS backups or arbitrary LXC remnants.
The follow-up clean installer handles known safe Proxmox runtime remnants.
HELP
}
while (($#)); do
  case "$1" in
    --destroy)
      [[ "$MODE" == preview ]] || die "Duplicate --destroy"
      MODE=destroy; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || die "Root on the PVE host required"
for cmd in pct pvesh python3; do
  command -v "$cmd" >/dev/null || die "Missing Proxmox command: $cmd"
done
[[ -r "$ROOT/bootstrap/check-controller-config.py" ]] ||
  die "Checkout incomplete: no controller identity validator"

inspect() {
  local cfg cluster
  cfg="$(pct config "$VMID")" || die "CT1001 does not exist; no reset to perform"
  python3 "$ROOT/bootstrap/check-controller-config.py" <<<"$cfg" ||
    die "CT1001 does not have the exact disposable controller identity"

  # Refuse any additional or host-backed mounts, data disks, backup locks,
  # snapshots, hooks or arbitrary low-level LXC directives. A new test CT
  # must match the single-rootfs topology created by this bootstrap.
  if grep -Eq '^((mp|unused)[0-9]+|hookscript|lock|lxc[.][^:]*|template|parent|snapstate):|^\[' <<<"$cfg"; then
    die "Additional disk, mount, snapshot, lock or hook detected; manual review needed"
  fi
  if grep -Eq '^rootfs: .*[,](acl|mountoptions|quota|replicate)=' <<<"$cfg"; then
    die "Unexpected custom rootfs features"
  fi
  # Only settings that the original single-controller bootstrap can
  # create are permitted. Any additional device, disk or security override
  # must be reviewed manually instead of invoking the destructive reset.
  python3 -c '
import sys
allowed = {
    "arch", "cores", "description", "hostname", "memory", "net0",
    "nameserver", "onboot", "ostype", "rootfs", "swap", "tags",
    "unprivileged",
}
for line in sys.stdin:
    if not line.strip():
        continue
    key, sep, value = line.partition(": ")
    if not sep or key not in allowed:
        raise SystemExit(f"Unexpected CT1001 config key: {key[:40]}")
' <<<"$cfg" || die "CT1001 has non-bootstrap settings; manual review needed"

  cluster="$(pvesh get /cluster/resources --type vm --output-format json)" ||
    die "Cluster VMID inventory unavailable"
  python3 -c '
import json, socket, sys
rows=json.load(sys.stdin)
if not isinstance(rows,list):
    raise SystemExit("Invalid cluster inventory")
matches=[r for r in rows if isinstance(r,dict) and r.get("vmid")==1001]
if len(matches)!=1 or matches[0].get("type")!="lxc":
    raise SystemExit("Cluster identity mismatched")
if matches[0].get("node")!=socket.gethostname().split(".")[0]:
    raise SystemExit("CT1001 belongs to another node")
' <<<"$cluster" || die "Cluster membership of CT1001 is not verified"

  printf '\n=== CT1001 DELETION SCOPE ===\n'
  grep -E '^(hostname|rootfs|tags|unprivileged|net0|memory|cores):' <<<"$cfg"
  pct status "$VMID" || die "Cannot inspect CT1001 status"
}

inspect
printf '\nOnly CT1001 and its Proxmox-managed rootfs will be destroyed.\n'
printf 'Existing vzdump/PBS backups are not deleted.\n'
printf 'Proxmox ACL/firewall entries for this CT are removed by pct destroy.\n'
printf 'No purge of backup, replication or HA jobs is requested.\n'

if [[ "$MODE" == preview ]]; then
  printf 'PREVIEW ONLY – NOTHING CHANGED. Use --destroy for explicit approval.\n'
  exit 0
fi

[[ -t 0 && -t 1 ]] || die "Destruction requires an interactive terminal"
read -r -p "Type DELETE 1001 to permanently destroy only this controller: " APPROVAL ||
  die "Approval cancelled"
[[ "$APPROVAL" == "DELETE 1001" ]] || die "Approval not granted"

# Revalidate immediately before destructive actions. Never use pct --force,
# ignore locks, or use --destroy-unreferenced-disks.
inspect
if pct status "$VMID" | grep -qx "status: running"; then
  echo "Requesting graceful shutdown of CT1001..."
  pct shutdown "$VMID" --timeout 60 ||
    die "Graceful CT1001 shutdown failed; no destroy attempted"
fi
pct status "$VMID" | grep -qx "status: stopped" ||
  die "CT1001 is still running; no destroy attempted"
inspect
pct destroy "$VMID" ||
  die "Proxmox rejected CT1001 destroy; inspect before retrying"

if pct config "$VMID" >/dev/null 2>&1; then
  die "CT1001 config unexpectedly remains; check PVE state"
fi
printf '\nCT1001_DESTROYED\n'
pct list
echo "If a runtime directory remains, use the clean bootstrap's verified quarantine flow."
echo "Do not manually remove /var/lib/lxc/1001 or unrelated host files."
