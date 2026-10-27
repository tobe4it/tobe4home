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


## Guided installation (experimental)

**Start from an existing Proxmox VE host** with root shell access, Git,
an SSH public key whose private counterpart is on your admin workstation,
and a functioning network.

For the **unmerged development prototype only** (PR #1), the single entry
command is:

```bash
git clone --depth 1 --branch feat/bootstrap-setup-wizard-20261027 https://github.com/tobe4it/tobe4home.git /root/tobe4home-bootstrap && bash /root/tobe4home-bootstrap/bootstrap/launch.sh
```

This clones version-controlled installer files and starts a guided host-side
session. Admin SSH public keys are discovered automatically from the original
sudo user's and Proxmox root's SSH login authorizations; the operator selects
a fingerprint instead of manually creating a public-key file. Keys with
restrictive authorized_keys options are skipped, and a public-key paste
option remains available if no existing login key is suitable.
When `whiptail` is already installed on Proxmox, the installer opens
a **Debian-style text-mode setup interface** (dialog boxes and selection menus).
Otherwise it uses a simple command-line fallback without installing packages
on the host. To enable dialogs explicitly on Proxmox, first review and install
the optional host package `whiptail` with `apt install whiptail`, then run
`bash /root/tobe4home-bootstrap/bootstrap/launch.sh` again.
To force the fallback, set `TOBE4HOME_INSTALLER_UI=text`.
An invalid underscore in the host prefix (e.g. `tb4h_`) prompts a validated
replacement suggestion (`tb4h-`), rather than aborting the entire setup. It proposes an unused VMID (preferably 1000), editable hostname
prefix, rootfs storage, bridge/VLAN and a public SSH key. It detects the Rocky
Linux 10 system template, prints a **read-only plan**, and creates a single
unprivileged setup LXC **only after** the explicit `INSTALL <VMID>` approval.
It does not perform a `curl | bash` remote-code execution.

**Security:** This is not a released installer. Review the code and the exact
Git commit before running it as root; the development branch is mutable.
Do not execute on production until the Proxmox acceptance tests in PR #1
have passed. After review and release, the entry command will be switched
to a pinned, verified stable release (not a moving feature branch).
If `/root/tobe4home-bootstrap` already exists, do not overwrite it:
review it and run `bash /root/tobe4home-bootstrap/bootstrap/launch.sh`.

The installation entry point starts **on a prepared Proxmox VE host**:
a preflighted script creates a dedicated, unprivileged Rocky Linux 10 LXC.
After health checks, it shows the guest's actual IPv4 address plus its
internal **HTTPS URL** (`https://<guest-IP>:8765/`), bootstrap username,
strong random setup code and self-signed certificate SHA256 fingerprint.
The wizard is directly accessible from the selected internal network,
subject to site firewall/routing policy; **no SSH tunnel is required**.
Its temporary certificate must be verified and replaced with a trusted
internal certificate. The wizard currently records an installation draft, discovers facts
from its own guest, and can export an **optional** local recovery starter.
It **does not yet provision** the essential Ansible/Git/Coding-Agent
infrastructure or execute prompt-derived Ansible deployments. This is the
next critical implementation, not a mandatory recovery-export step.
Production deployments require independent approval.

The first Proxmox Realtest exposed a probable `umask 077` / uid-mapped
rootfs traversal issue; `pct create` now runs with isolated `umask 022`
while secret files retain restrictive permissions. The rootfs access fix
and direct LAN connectivity are not yet verified on the user's host.

See [guided bootstrap and installation gates](docs/BOOTSTRAP.md) and
the [prompt-driven installation orchestrator architecture](docs/INSTALLATION-ORCHESTRATOR.md).
