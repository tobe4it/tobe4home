# Bootstrap from Proxmox: tobe4home setup path

Status: **prototype / review only**. The stage-0 code creates one dedicated LXC
after explicit operator approval; it does not install Forgejo, Ansible, identity
services or AI, and the web application does not trigger system changes.

## Goal

A new household starts with a working Proxmox VE host, a management workstation
and an SSH public key. A small host-side bootstrap creates one isolated
RHEL-compatible setup LXC. Its local-only web wizard records an initial
non-secret configuration **draft** and shows the prerequisites in sequence.

Long-term, versioned blueprints and constrained coding agents will produce
Ansible changes, run tests and open review requests in internal Forgejo.
Deployment will remain explicitly authorized and independently auditable.
Prompts are requests to the engineering pipeline, **not executable installers**.

## Supported stage-0 boundary

- Proxmox VE remains the virtualization layer (its host OS is not replaced).
- A Rocky Linux 10 system template from the official Proxmox catalog is
  selected by default. If absent locally, it is downloaded *after* `--apply`
  and before the new LXC is created. Read-only preview performs no download.
- The CT is *unprivileged*, no nesting, no Docker/Podman socket access,
  no privileged mounts, no production credentials and no auto-start.
- Guest SSH uses a dedicated non-root user and the supplied public key;
  password authentication and guest root SSH are disabled.
- The wizard is reachable directly over authenticated **HTTPS on the selected
  internal LXC network**. Its URL is `https://<guest-IP>:8765/`. The installer
  generates a temporary self-signed certificate with the actual guest-IP SAN
  and a strong random setup code. Neither unauthenticated HTTP nor public
  Internet exposure is part of stage 0.
- The wizard saves only a local `site.local.json` (0600) containing non-secret
  preliminary answers, not installation approval. Its contents never go to Git.
- LXC isolation does not guarantee the SELinux properties of a RHEL VM.
  Evaluate a small Rocky VM for subsequent Podman/SELinux workloads where
  enforcing SELinux or stronger isolation is a hard requirement.
- The installer uses `dnf` to install Python and OpenSSH within this **new**
  guest. Guest package repositories and DHCP must therefore be reachable.
- No unattended actions are taken against existing containers or VMs.

## Operator prerequisites

A working, independently administered Proxmox VE host, functional storage with
`rootdir` support, a Linux bridge with DHCP/network reachability, available CT
ID, a usable Rocky Linux 10 template in the official Proxmox catalog,
an admin workstation with SSH client and a dedicated **public** SSH key. Review guest firewall policy: allow SSH only
from a trusted management path. Maintain a separate host console/recovery
login. Take a backup of the Proxmox host's relevant configuration.

Discover storage/bridge/template **on your actual node**:

```bash
pveam available --section system | grep -Ei 'rocky|alma'
pveam list local
pvesm status
ip -br link
```

The script discovers the newest available official Rocky Linux 10 template
from the Proxmox catalog and checks whether it is cached. During preview
it merely reports the anticipated download. With `--apply`, it refreshes the
official catalog, downloads the selected template if needed, then rechecks
VMID/network eligibility before creating the guest. If the template catalog
is unavailable, do not substitute an unverified URL. Update guest packages
after installation to the current supported Rocky Linux 10 minor release.

## Network choice and internal reachability

**Recommendation:** choose the bridge connected to the operator's internal
network where the setup guest can be reached by the administrator via SSH,
directly or through an allowed jump host. The administrator knows their own
network mapping; the bootstrap does **not** attempt to infer or ask for an
extra role such as IoT, internal or DMZ. A VM bridge's number is not a VLAN
tag and the host's default route does not prove guest reachability.

The setup wizard lists active Proxmox bridges, including VLAN-awareness.
Selecting a VLAN-aware bridge offers an optional tag (1–4094); a
non-VLAN-aware bridge is used untagged. The selection never changes physical
switches, VLAN membership, firewall rules or network routes.

**Stage-0 browser access:** after successful installation, the admin opens
`https://<guest-IP>:8765/` directly from the selected internal network.
The service listens on the guest IPv4 network interfaces, is protected
by TLS and requires username `setup` plus a generated strong setup code.
The self-signed certificate is initially valid for 30 days; the installer
prints the SHA256 fingerprint, which the operator must verify before trusting
the certificate. The code remains valid until it is deliberately rotated or
replaced by the future identity service. A routing/firewall rule could
allow connections from other subnets despite the VLAN choice; site-specific
network ACLs remain necessary. DHCP, outbound DNS/package access and actual
reachability from the operator workstation are not proven merely by a
selected bridge being UP. Do not publish port 8765 to the Internet.

In a site-specific installation an operator might know that `vmbr3` is
the internal bridge. That information belongs in local configuration, **not**
as a universal default in public tobe4home code.

## SSH authentication: reuse an existing administrative public key

Before a guest exists, the installer can reuse an SSH **public** login key from
the existing administrative login to Proxmox. It checks the invoking sudo
account (e.g. `lxadmin`) first, then Proxmox root's `authorized_keys`, whose
usual symlink may resolve into `/etc/pve/priv/authorized_keys`. It displays
each eligible key's source, algorithm and SHA256 fingerprint, and the operator
selects the key already held by their workstation (e.g. Termius). Only the
selected **public** key is installed for the non-root `tobe4home` guest account.

The installer's key discovery never reads the private-key files `id_rsa` or
`id_ed25519`; a host's `id_rsa.pub` is not assumed to be the admin's
workstation credential. `authorized_keys` entries with restrictive options
(`from=`, `command=`, `restrict`, etc.) are **not** carried over with
their restrictions removed: such entries are excluded and may require
a different approved key. Duplicate keys are merged by fingerprint.

Selected public-key material is staged in an owner-only temporary file under
`/run` (0600) and deleted on every normal cancellation or exit. The core
bootstrap script validates it again with OpenSSH before creating a guest.
No private material is copied, output in logs, or sent to the repository.

If no suitable authorized login key can be found (for example, if the
operator uses password authentication), the console wizard offers a direct
**paste-public-key** option. That requires the operator to supply the
workstation's public key; an SSH session alone does not reliably convey
its private-key counterpart to the server. The UI should not generate a
server-held private key as an implicit workaround.

This selection is for access to the new setup LXC, **not** for obtaining or
granting privileged access to Proxmox. The network still needs to allow
SSH from the admin workstation or an explicitly permitted jump host.

## Text-based interactive installer (Debian-style menus)

The launcher automatically uses the system `whiptail` utility when available
and when attached to a capable interactive terminal. It displays a welcome
dialog, validates the chosen VMID, proposes a prefix and explains why
underscores cannot be used in DNS hostname labels (e.g. `tb4h_` becomes
the explicitly confirmed `tb4h-` suggestion). Active storage, bridge and
VLAN are chosen from read-only Proxmox discovery. The public SSH key is
validated before any installation is permitted.

Storage selection uses the supported, read-only Proxmox command
`pvesm status --content rootdir` and offers only **active** LXC-capable
storages. It does not use an unsupported `pvesm config <name>` call. A
previous installer draft incorrectly hid `local-zfs`; this has been corrected
and regression-tested.

No packages are installed on the Proxmox host automatically. When `whiptail`
is missing, the launcher falls back to the original command-line questions.
An operator may explicitly install `whiptail` with the host's normal apt
package manager after review, or run `TOBE4HOME_INSTALLER_UI=text bash
bootstrap/launch.sh` to always use plain text mode. Cancellation in the
dialog interface exits without starting a deployment; invalid choices remain
on the current screen. A fully navigable multi-step back button is planned,
but is **not** implemented in this prototype.

At the end, a complete read-only preflight is shown. Only the exact explicit
confirmation `INSTALL <VMID>` authorizes image download or CT creation.
The dialog cannot bypass the independent host script's checks.

## First run: one command, guided choices, explicit approval

The guided entry point is `bootstrap/launch.sh`. It runs on an existing
Proxmox node, discovers the cluster VMID allocation read-only, proposes the
first free number in 1000–1999, and collects a guest hostname prefix, rootfs
storage, bridge, optional VLAN and an existing public SSH key.

Until PR #1 is merged and a verified release is published, use the **reviewed
development branch only on a test host**:

```bash
git clone --depth 1 --branch feat/bootstrap-setup-wizard-20261027 https://github.com/tobe4it/tobe4home.git /root/tobe4home-bootstrap && bash /root/tobe4home-bootstrap/bootstrap/launch.sh
```

The entry command downloads the Git repository but does **not** pipe a network
response straight into a root shell. The branch can change: review the commit
SHA and source prior to execution. The installation must only be used for a
real Proxmox test after PR checks and operator approval. Do not run unreviewed
changes on live infrastructure.

The interactive flow displays one combined **read-only preflight plan** and
then demands the exact phrase `INSTALL <VMID>`. Only after approval does it
download the official Rocky Linux 10 template (if not already cached) and
attempt to create the one unprivileged setup guest.

For repeat operation from an existing reviewed checkout:

```bash
bash /root/tobe4home-bootstrap/bootstrap/launch.sh
```

For automation or a custom environment you may also invoke the underlying
`bootstrap/bootstrap.sh` directly with explicit options. Without `--apply`,
this is a read-only preflight:

```bash
bash bootstrap/bootstrap.sh \
  --vmid 1000 --storage local-zfs \
  --bridge vmbr2 --vlan-tag 42 \
  --container-prefix house- \
  --ssh-public-key /root/.ssh/id_ed25519.pub
```

Those bridge/VLAN/key values are **illustrative only**. The production
network must be chosen based on actual management access, DHCP, routing,
package repositories and firewall restrictions. Do not assume that vmbr2
is VLAN 2 or that a Proxmox host IP proves guest reachability.

The VMID `1000` is a **tobe4home numbering convention**, not a hardcoded
requirement. Prefer an installation-specific free `1000–1999` range; retain
other VMID ranges for existing deployments and legacy guests.

| VMIDs | Planned use |
| --- | --- |
| 1000 | Setup wizard / recovery entry point |
| 1001–1099 | Core services, Ansible, internal Git, identity |
| 1100–1199 | AI, coding agents, Langflow |
| 1200–1899 | Optional family services |
| 1900–1999 | Development and test instances |

The script rejects occupied VMIDs cluster-wide; **recheck at deployment
time** because the earlier cluster listing may be stale. Bridge, VLAN, storage
and SSH public-key path are site-dependent examples that must be verified.
`vmbr2` is not VLAN 2: tags such as VLAN 42 are independent and accepted only
on an active VLAN-aware bridge. A selected bridge/tag does not establish
that DHCP, SSH or upstream routing is available.

**Hostnames and VMIDs are separate choices.** The proposed hostname prefix is
`tobe4home-`; the operator may overwrite it during interactive bootstrap,
set it with `--container-prefix house-`, or adjust the proposal later in the
web wizard. The actual initial LXC hostname becomes `house-setup` in that
example. Acceptable prefixes are lowercase DNS-label characters, max 57
characters excluding a trailing `-`; the resulting LXC hostname cannot be
longer than 63 characters. Changing the wizard preference affects *future*
service deployments, never renames the existing setup LXC.
VMID `1000` remains independently selectable.

The template is a base snapshot, not a promise that the included packages
match the newest Rocky Linux 10 minor release. Update the new guest to the
latest supported release and apply security errata.

**Default OS: Rocky Linux 10** (latest supported 10.x minor). Rocky Linux
9 is a documented compatibility fallback only. Rocky Linux 10 on AMD64
requires x86-64-v3: verify host CPU support first (and for later VMs ensure
the virtual CPU model exposes it). For Podman, SELinux enforcing and
isolation-sensitive application workloads, prefer an RHEL-compatible
virtual machine if the required properties cannot be guaranteed in LXC.

The script leaves the newly created CT intact after partial failures for
inspection rather than destroying it. Use `pct exec <VMID> -- journalctl -u
tobe4home-wizard` and `pct config <VMID>` for diagnosis. Never automatically
delete a partially installed CT without independent review.

## First real Proxmox acceptance: 2026-10-27

On a Proxmox VE 9.2 system, the **first real installation attempt** passed
read-only checks, downloaded `rockylinux-10-default_20251001_amd64.tar.xz`
from the official Proxmox catalog, and verified its checksum. It failed at
the next operation, `pct create --unprivileged 1 --rootfs local-zfs:8`, with:

```text
tar: /var/lib/lxc/1000/rootfs: Cannot open: Permission denied
unable to create CT 1000 - command 'lxc-usernsexec ... tar ...' failed
```

This is a **rootfs access / unprivileged-idmapping** failure, not proof
that Rocky Linux 10 cannot run. A strong, testable cause was found in the
bootstrap itself: its security-oriented global `umask 077` was inherited by
`pct create`, while the failed installation left
`/var/lib/lxc/1000/rootfs` as `root:root` with mode `0700`. Proxmox's
unprivileged template extractor runs with mapped host uid 100000 and cannot
traverse this root-only directory. The `pct create` subprocess now runs with
a scoped `umask 022`, while the bootstrap preserves restrictive permissions
on secrets. This is a **probable root cause**, not yet a real-world verified fix.
Storage ACL settings and pre-existing paths still require inspection.

**Operator safety:** do not rerun the deployment, use a privileged container,
alter ZFS ACL properties, run `chmod`/`chown` on shared host directories,
or destroy leftover CT/dataset files as a workaround. Collect read-only
diagnostics first:

```bash
sudo pct status 1000 || true
sudo pct config 1000 || true
sudo pvesm status --content rootdir
sudo namei -l /var/lib/lxc/1000/rootfs
sudo ls -ldn /var/lib/lxc /var/lib/lxc/1000 /var/lib/lxc/1000/rootfs 2>&1
sudo getfacl -p /var/lib/lxc/1000 /var/lib/lxc/1000/rootfs
sudo findmnt -T /var/lib/lxc/1000/rootfs -o TARGET,SOURCE,FSTYPE,OPTIONS
sudo zfs list -o name,mountpoint,acltype -t filesystem |
  grep -E '(^NAME|1000|rpool/data)'
sudo zfs get -r -o name,property,value acltype,aclmode rpool/data
sudo ls -l /etc/subuid /etc/subgid
```

Replace `rpool/data` with the actual configured zfspool pool if different;
`grep` is advisory, not a storage dataset selector. Inspection commands may
report expected `not found` errors if the failed `pct create` cleaned up
the partial guest. Never interpret absent paths as successful creation.

The revised `bootstrap/host_preflight.py` now checks glibc CPU
`x86-64-v3` eligibility, active LXC rootdir-capable storage, a non-destructive
Proxmox uid/gid usernamespace smoke test, ZFS properties (where discoverable)
and stale CT paths **before template download or create**. A read-only test
cannot conclusively prove a future ZFS subvolume's access or guest DHCP.
Therefore a live, isolated test and independent authorization are still
required. Failed creation must preserve diagnostics and not trigger automatic
cleanup of resources it did not create.

## Direct internal HTTPS after successful install

Once `pct create`, guest provisioning, systemd activation and an authenticated
HTTPS request to the guest's `eth0` IP all succeed, the terminal and whiptail
success dialog show the **real** assigned guest IP and a direct URL:

```text
STAGE-0 READY: CT 1000
Guest IPv4: <actual-guest-IP>
HTTPS + login health: PASS (inside guest)

WEBAPP URL (selected internal network):
  https://<actual-guest-IP>:8765/

LOGIN USER: setup
SETUP CODE: <generated-random-code>
SHA256 Fingerprint=<certificate fingerprint>
```

Access directly from the internal management workstation (no SSH tunnel
required). Since the certificate is initially self-signed, verify its
fingerprint **before entering the setup code**; replace it later with a trusted
internal certificate. The bootstrap checks authentication and HTTPS on the
guest IP from within the guest, but **cannot prove client-to-guest routing
or firewall reachability** from every administrative workstation.
Never enable unauthenticated HTTP to work around those network controls.

## Access the initial web wizard

Find the guest address using the Proxmox UI or
`pct exec <VMID> -- hostname -I`. From your **workstation**:

```bash
ssh -N -J <pve-ssh-user>@<pve-address> \
  -L 8765:127.0.0.1:8765 tobe4home@<guest-address>
```

Visit `http://127.0.0.1:8765/` in the workstation browser.
It is plain HTTP only **inside** the encrypted SSH local tunnel, never
directly exposed to the LAN. Ensure the host, guest SSH routing and firewall
allow the trusted jump path. If you already have a local tunnel on port 8765,
choose a different local source port while keeping the remote side at 8765.

The web form records:

1. Editable guest hostname prefix (default: the value selected during bootstrap).
2. Human-readable installation label.
3. Private site's base DNS domain (stored only in the guest).
4. Timezone and DNS resolver IP.
5. Independent backup destination *category*.

It does **not** ask for passwords, API tokens, email credentials, private
keys, payment data or user identity lists. It performs input validation, CSRF
checking, no-store responses and atomic owner-only local saves.

## Required platform milestones

| Gate | Prerequisites | Independent acceptance evidence |
| --- | --- | --- |
| 0 Bootstrap | Proxmox + setup LXC | no collisions, local-only wizard, no existing guest changes |
| 1 Recovery foundation | offline bootstrap, Git, Ansible, encrypted site vars | recovery without Git/AI/OIDC services |
| 2 Data protection | backups and outside-host copy | actual isolated restore, secrets recovery |
| 3 Internal Git | Forgejo supported LTS, dedicated CI runner | PR/branch rules, no production runner secrets |
| 4 Secure identity | OIDC + TLS + system-level authorization | adult/child cross-user denial tests |
| 5 Local AI development | own LLM, sandboxed coding agent | code edit, tests, PR, human approval |
| 6 Orchestration | Langflow + scoped MCP tools | user-scoped tool access, auditable runs |
| 7 Service catalog | BookStack/Paperless/mail/etc. as independent modules | idempotence, backup/restore, auth and rollback tests |

The setup wizard will later become a guided **plan-first** installer. Each
installation gate must be independently checked; write operations require
explicit approval. If a prerequisite is unavailable, the wizard must stop or
provide documented manual recovery, not silently weaken security.

## Platform engineering policies

- LTS or longest supported security-maintained stable version, never
  unsupported versions merely because they were called LTS.
- Prefer RHEL-compatible guests (Rocky/AlmaLinux) for new deployments.
- Prefer rootless Podman, systemd Quadlet and SELinux enforcing **where
  supported and actually tested**; use a VM if LXC restrictions prevent this.
- Source of truth remains Git, with environment-specific configuration outside
  public Git and secrets encrypted and separately recoverable.
- Deterministic tasks, tests and actual deployments remain in Ansible;
  no LLM gets direct privileged hypervisor access.
- CI runners are separate from Forgejo and the deploy controller.
- Every Ansible run should show the full ordered task timing recap using
  `ansible.posix.profile_tasks` after verifying the installed plugin version.
- Forgejo can be restored *without itself*: maintain an offline, read-only
  bootstrap copy and separately protected recovery keys.

## Next implementation tasks

1. Mock-based end-to-end tests for host script command invocation and failures.
2. Web stepper with read-only detection of host resources through an explicit
   narrow authenticated interface, not direct LXC root access.
3. Signed/versioned blueprint schema with dependency checks and plan preview.
4. Secure approval gateway separating operator identity from agent identity.
5. First offline-recoverable Ansible controller blueprint and restore tests.
6. Forgejo LTS, backups, SSH/OIDC, isolated runners and tested cut-over.
7. Local agent orchestration, then Langflow; no unreviewed autonomous deploys.

For privacy constraints see [site-local configuration](SITE-LOCAL-CONFIGURATION.md)
and the engineering standard in `ENGINEERING.md`.
