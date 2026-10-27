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
- A predownloaded, reviewed Rocky Linux or AlmaLinux 9/10 LXC system template
  is required; verify provenance and the actual template filename.
- The CT is *unprivileged*, no nesting, no Docker/Podman socket access,
  no privileged mounts, no production credentials and no auto-start.
- Guest SSH uses a dedicated non-root user and the supplied public key;
  password authentication and guest root SSH are disabled.
- The wizard is reachable **only on 127.0.0.1 in the guest**. Administrators
  must establish an SSH local tunnel through the Proxmox host.
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
ID, usable Rocky/AlmaLinux LXC template, admin workstation with SSH client and
a dedicated **public** SSH key. Review guest firewall policy: allow SSH only
from a trusted management path. Maintain a separate host console/recovery
login. Take a backup of the Proxmox host's relevant configuration.

Discover storage/bridge/template **on your actual node**:

```bash
pveam update
pveam available --section system | grep -Ei 'rocky|alma'
pveam list local
pvesm status
ip -br link
```

If the template is not already present, select an actual available filename
from `pveam available` and download it manually with `pveam download`.
Do not assume a template version or filename from this documentation.

## First run (preview, then explicit apply)

Clone this repository on the Proxmox host from a **reviewed commit**; never
pipe downloaded code into a root shell. Use an unused VMID and adjust all
placeholders to the real host's configuration:

```bash
git clone https://github.com/tobe4it/tobe4home.git
cd tobe4home
# For evaluation, check out the reviewed feature branch/commit explicitly.
bash bootstrap/bootstrap.sh \
  --vmid 700 \
  --template 'local:vztmpl/ACTUAL_ROCKY_10_TEMPLATE.tar.zst' \
  --storage local-lvm --bridge vmbr0 \
  --ssh-public-key /root/.ssh/id_ed25519.pub

# Only after checking all displayed preflight information:
bash bootstrap/bootstrap.sh \
  --vmid 700 \
  --template 'local:vztmpl/ACTUAL_ROCKY_10_TEMPLATE.tar.zst' \
  --storage local-lvm --bridge vmbr0 \
  --ssh-public-key /root/.ssh/id_ed25519.pub --apply
```

The VMID `700` and other names above are examples, not reserved defaults.
The script refuses existing CT/VM IDs cluster-wide. Do not use any CT ID
reserved for migrated legacy workloads. Template name must be replaced with a
real cache file; this example deliberately cannot be executed unchanged.

The script leaves the newly created CT intact after partial failures for
inspection rather than destroying it. Use `pct exec <VMID> -- journalctl -u
tobe4home-wizard` and `pct config <VMID>` for diagnosis. Never automatically
delete a partially installed CT without independent review.

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

1. Human-readable installation label.
2. Private site's base DNS domain (stored only in the guest).
3. Timezone and DNS resolver IP.
4. Independent backup destination *category*.

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
