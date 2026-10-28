# tobe4home

**Self-hosted home infrastructure, reproducibly managed with Ansible.**

tobe4home is a modular Infrastructure-as-Code project for people who want to operate selected services on their own hardware. It focuses on reproducible deployments, isolated containers, identity and access management, networking, backups, and transparent operations.

## Project scope

- Proxmox VE and Linux containers
- Reverse proxy and certificate automation
- Identity, authentication and single sign-on
- DNS filtering, MQTT and smart-home integration
- Mail, documents and locally hosted AI
- Monitoring, validation, backup and recovery
- German and English operator documentation

Components are independently selectable. A working installation does **not** require all of them.

## Security and privacy

Real hostnames, addresses, personal domains, credentials and site-specific secrets are deliberately excluded from the published configuration. Use example files as templates and keep your private settings outside Git.

Do not deploy example addresses or placeholder credentials to production. Review each Ansible playbook before running it, especially any task that changes configuration or services.

## Status

The initial import of reviewed infrastructure components is complete. The independent public Git history starts with this project, not with earlier environment-specific development commits.

The automated validation workflow currently checks Python contracts and bilingual handbook sources. This is an **infrastructure-as-code development baseline**, not a turnkey installation: integration tests against independent live environments, a full manual security review, and a stable release remain outstanding.

## Documentation

English and German setup and operations documentation is available under `docs/` and `docs/handbook/`. A newcomer path starts with infrastructure prerequisites and basic security; advanced integrations are optional.


## Installation status: direct CT 1001 test installer

**Experimental single-controller first-install path is implemented in the
development branch; not yet validated by a live Proxmox acceptance run.**

The obsolete two-container Stage-0+Stage-1 chain is no longer used by
`bootstrap/launch.sh`. The launcher now starts
`bootstrap/single-controller.sh`, which discovers resources read-only,
prompts for network/storage/DNS and an existing administrative SSH public
key, and prints a preview before the explicit `INSTALL 1001` approval.
The intended target is **only CT 1001** (`tb4h-controller`), an
unprivileged Rocky Linux 10 LXC with 4 vCPU, 4096 MiB RAM, 40 GiB
rootfs and onboot disabled while testing.

Once CT 1001 is created, the installer checks guest DNS and starts
a **source-patched AnsibleForms 7.4.2 native/systemd installer**.
The script verifies the immutable official upstream Git commit
`ae60b31742ee5bd6956f9bf9798fd5b5356ccf42`, builds it using
Go 1.27.2 with upstream Go module checksums, and changes only the Node
version-selection function to force `v26.12.1`. The downloaded Node
archive is still verified by the original official SHA-256 procedure.
AnsibleForms installs MariaDB and an independent Ansible Runtime Environment. The
web portal is expected on HTTPS port 443. No Docker or Podman nesting
is required for this first run. The generated admin password is printed
to the operator; do not post it in public logs.

**Do not confuse this with a finished self-provisioning platform:**
the automatic tobe4home forms, live Proxmox API credentials, OpenTofu
state/approval/executor gateway, CI and guest configuration workflows
still require actual integration and acceptance. No additional guests
are created by this bootstrap.

### Node.js release publication gate (28 October 2026)

On the second clean Rocky Linux 10 controller bootstrap, the upstream
AnsibleForms 7.4.2 native installer selected **Node.js v26.13.0**
from the current Node.js release index but could not retrieve
`https://nodejs.org/dist/v26.13.0/SHASUMS256.txt`. It aborted with
`STOP: AnsibleForms installer failed; CT1001 kept for --resume`.
This is not a Proxmox, Rocky DNF or ZFS error. The immediately previous
run had selected v26.12.1; the upstream installer selects the highest
Node.js 26 release **at runtime** rather than a fixed patch version.

**Resolved for tobe4home with a pinned-source installer build.**
The original official binary cannot accept a specific Node 26 patch
version; preinstalling Node does not override its `latestNode` selector.
The bootstrap now verifies the original **AnsibleForms v7.4.2 source
commit SHA**, uses `Go 1.27.2` and the upstream module sums to compile
the installer, and applies a very narrow source patch to `latestNode`.
When `TOBE4HOME_NODE_VERSION=v26.12.1` is present, the installer
selects exactly that version. It refuses any other pin and performs its
original SHA-256-verified Node archive download.

The preflight checks the official **v26.12.1** SHA-256 manifest and
linux-x64 tarball on both the Proxmox host (before VMID allocation) and
inside the new guest (immediately before install). It does not consult
the inconsistent `latest` index. All software remains downloaded from
the original trusted origins; no Node tarballs or secrets are committed
to Git, and the container remains unprivileged.

**This native installer binary is locally built from a verified official
source commit with a reviewed one-function patch; it is not identical
to the official published binary.** The GitHub CI independently compiles
the same patched Go source to catch build regressions. The next live
Proxmox clean-install and browser login must still pass acceptance.

For a deliberately disposable CT1001 from the failed attempt, run the
guarded `bootstrap/reset-controller.sh` preview and confirmed destroy,
then run the clean installer with the reviewed network/storage options.
The first-login URL + generated password must appear as the **last**
output, only after successful local HTTPS and systemd health checks.

### First login credentials at the very end of bootstrap

A completed controller bootstrap must not leave the user searching through
earlier package-manager or upstream installer output for a password.
**Only after all systemd services and the local HTTPS healthcheck succeed**
does the final guest-side step display a single terminal panel with:

- actual guest HTTPS URL derived from the live `eth0` IPv4 address;
- AnsibleForms initial username;
- the original generated initial admin password;
- notice about the self-signed certificate and changing the password.

The initial values are read **inside CT1001** from the existing,
root-protected `/opt/ansibleforms/app.env`. The bootstrap checks the
file type, owner, hardlink count, permissions and exact expected variables;
it does not print the DB password or RTE token. There is no copy of
`app.env`, no password in a command argument, GitHub file, systemd
journal, or host-side temporary file. Credentials are deliberately
visible in the attended terminal, so the operator must not paste the
final output into an issue or chat.

The final panel is the **last output** of a successful bootstrap, directly
before the first browser login. If installation/health fails, it is
withheld. After a partial failure, `--resume` preserves the existing
credentials and displays the same initial values once the health gates
pass. The initial password might no longer work if it was subsequently
changed in the WebUI; this routine does **not** reset credentials.

```text
TOBE4HOME – CONTROLLER BEREIT, JETZT ANMELDEN
Adresse:  https://<private-guest-IP>/
Benutzer: admin
Passwort: <originally-generated-initial-password>
```

### Verified clean reset of disposable CT1001

For a deliberately discarded, partially installed test controller, use
the dedicated guarded reset tool instead of an unrestricted `pct destroy`
or `rm -rf`. It verifies the existing VMID, normalized exact ownership
tags, `tb4h-controller` hostname, unprivileged status, rootfs identity,
cluster node, and lack of custom mountpoints or other non-bootstrap
configuration. The default mode is **read-only**. Actual deletion requires
a separate `--destroy` invocation and the literal `DELETE 1001`.

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash /root/tobe4home-bootstrap/bootstrap/reset-controller.sh
sudo bash /root/tobe4home-bootstrap/bootstrap/reset-controller.sh --destroy
# Type DELETE 1001 only after inspecting its exact identity and rootfs.
sudo pct list
```

The script gracefully shuts down only CT1001 before issuing Proxmox's
`pct destroy 1001`. It **does not** use `--purge`,
`--destroy-unreferenced-disks`, `--force` or recursive filesystem
removal. Proxmox-managed CT1001 rootfs and CT-specific firewall/ACL
records are removed; external vzdump/PBS backups are not deleted.
If CT1001 has additional drives, bind mounts, snapshots, hooks,
unrecognized config fields or a mismatched identity, the reset fails
closed for manual review. Any residual `/var/lib/lxc/1001` files are
handled only by the separately reviewed clean-bootstrap quarantine
logic after `INSTALL 1001`.

**All in-guest AnsibleForms passwords, initial admin credentials and
database contents in CT1001 will be lost.** Only do this for a disposable
bootstrap test, never an established controller.

### Next clean-install attempt on Proxmox

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash /root/tobe4home-bootstrap/bootstrap/launch.sh
# Inspect the read-only plan. No resources change.
sudo bash /root/tobe4home-bootstrap/bootstrap/launch.sh --apply
# Inspect again, type exactly INSTALL 1001.
```

Use a verified reachable DNS resolver for the guest. SSH keys are
selected from existing authorized login keys by fingerprint; no
private key crosses into the container. Do not use legacy
`bootstrap/bootstrap.sh` or `bootstrap/deploy-ansible-controller.sh`
for a fresh installation.

### Repeat-install remediation after deletion of old CT1001

A deleted guest may leave an **empty** local runtime directory
`/var/lib/lxc/1001`, even though the CT config and rootfs storage volume
no longer exist. The read-only host preflight now reports this as a WARN;
after the exact `INSTALL 1001` confirmation, the bootstrap independently
rechecks cluster VMID, CT config and rootfs volumes, then uses **`rmdir`
only** on that completely empty directory. It never recursively deletes
LXC data.

A special, previously verified Proxmox-generated remnant is now also
supported: **exactly one regular `rules.seccomp` file (up to 4 KiB)
plus a completely empty `passthrough` directory**, with no mountpoints.
The preview displays WARN. Only after `INSTALL 1001`, the installer
rechecks the Proxmox VMID and rootfs storage and atomically **moves**
this entire remnant to the root-only
`/var/lib/tobe4home/ct-runtime-quarantine/` directory. It never deletes
the seccomp file; the quarantine is recoverable by an administrator.

Other nonempty directories, symlinks, mountpoints or unreadable content
**still FAIL CLOSED**. Inspect them without making changes:

```bash
sudo ls -ld -- /var/lib/lxc/1001
sudo find -P /var/lib/lxc/1001 -mindepth 1 -maxdepth 2 -printf '%y %p\n'
sudo pct config 1001
sudo pvesm list local-zfs --content rootdir | grep -E '1001|Volid' || true
```

Do **not** use `--resume` when `pct config 1001` says the guest does not
exist. Resume is only for a partially provisioned CT actually owned by
this installer. A default gateway IP is not necessarily a working DNS
resolver; guest repository resolution is verified before invoking DNF.

If CT 1001 is created but DNF or the native AnsibleForms installer
fails, **do not recreate or delete it**. After diagnosing the failure:

```bash
sudo bash /root/tobe4home-bootstrap/bootstrap/launch.sh --resume
# Inspect exact CT1001 identity; type RESUME 1001.
```

### Native AnsibleForms file permissions (200/CHDIR) and automatic recovery

The first real native AnsibleForms 7.4.2 controller installation exposed a
**restrictive umask regression**: `bootstrap/install-ansibleforms-native.sh`
was invoked with `umask 077`, while upstream uses directory modes such
as 0755 without forcing them after creation. This produced root-owned
0700 release/runtime folders. The `ansibleforms` systemd user could not
enter `/opt/ansibleforms/current/server` and both services restarted with
`status=200/CHDIR`.

**Fixed for every new bootstrap:** the verified native installer itself
now runs under `umask 022`, leaving program directories traversable.
Its credential files use upstream-restricted modes. Future native
releases must retain this scoped umask rather than overriding global
host/guest security defaults.

**Automatic, idempotent recovery of an already-created CT 1001:**

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash /root/tobe4home-bootstrap/bootstrap/launch.sh --resume
# Confirm RESUME 1001 (only the verified existing tb4h-controller)
```

The resume path detects the existing systemd units, pushes
`bootstrap/repair-ansibleforms-permissions.py`, repairs only the
root-owned **release/runtime code paths** that the `ansibleforms` user
cannot already read/traverse, makes only `app.env` and `rte.env`
group-readable to the dedicated service group after verifying ownership,
resets/restarts the two native services, and checks local HTTPS. It
**never reruns the upstream first-install** when both systemd units
are present, and does not overwrite the database, generated secrets,
administrator account, or certificates. Symlink targets are not followed.
Persistent data, SSH keys, backups and TLS key material are outside the
repair scope. Unknown code ownership or unexpected permissions fail closed.

### Proxmox LXC tag normalization on resume

The first real resume after the native-umask bug exposed another gate issue:
the old shell check expected the text `tags: tobe4home;controller` in a
fixed order. Proxmox may return `tags: controller;tobe4home`.
The controller had already been created, and the old check returned
`STOP: Not the tobe4home controller` **before making changes**.

`bootstrap/check-controller-config.py` now validates **exact,
semicolon-delimited tag membership in any order** and separately checks
hostname `tb4h-controller`, `unprivileged: 1` and the expected CT1001
rootfs. The new check is read-only and runs before the `RESUME 1001`
confirmation. Nonmatching, duplicate or missing identity fields fail closed.
The previous order-sensitive grep was removed.

After updating the branch, retry the existing CT 1001:

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash /root/tobe4home-bootstrap/bootstrap/launch.sh --resume
```

Only the already-created controller is targeted; **do not** run `--apply`
again or remove the guest. A further failure must be analyzed without
recreating the database or disclosing admin credentials.

The process remains **staged**, not a fully released auto-provisioning
platform: AnsibleForms login/real workflow validation, OpenTofu backend
and apply approval, and subsequent independent guest deployments
must pass real acceptance before unattended bootstrap is enabled.

The new path must still pass a live Proxmox/DNS/LXC/HTTPS acceptance
test before being called a released installer. The branch is mutable;
inspect the Git diff and CI before running host-root provisioning.

The previous test guests CT 1000 and CT 1001 were deleted on
28 October 2026. The new clean-install test has no dependencies on
their old local state. [Development planning and integration status]
(docs/CONTROLLER-INTEGRATION.md) documents read-only inventory,
graphical topology preview and OpenTofu plan-generation work.
