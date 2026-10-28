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


## Installation status: single-controller bootstrap in development

**No new installation is currently enabled.** The earlier Stage-0 wizard
created a separate `*-setup` LXC, then required a second Ansible LXC.
That design is obsolete and conflicts with the accepted
[Single-Controller architecture](docs/ADR-001-SINGLE-CONTROLLER.md).

The new installer will collect only initial Proxmox options in its host
terminal menu and create **one** permanent controller LXC, normally
CT 1001, with [AnsibleForms](docs/ADR-002-ANSIBLEFORMS-UI.md)
and an Ansible/OpenTofu runtime. That controller will discover
infrastructure, show a reviewable plan, obtain explicit approval and
install only approved additional guests.

Until this controller bootstrap and its end-to-end Proxmox acceptance
tests are implemented, **`bootstrap/launch.sh` intentionally exits with
code 3 and prints an explicit not-ready message before any write**.
Do not use `bootstrap/installer-tui.sh` or
`bootstrap/bootstrap.sh --apply` to bypass the restriction: these
are the deprecated two-container prototype, retained for regression tests.

The repository already contains a non-mutating
[development preview and integration guide](docs/CONTROLLER-INTEGRATION.md)
for the read-only Proxmox inventory exporter, deterministic planner,
HTML topology, synthetic AnsibleForms wizard and OpenTofu HCL preview.
**Neither AnsibleForms nor OpenTofu is yet installed by this branch.**
The generated OpenTofu configuration does not call `apply`.

The former test guests CT 1000 and CT 1001 were explicitly removed from
the test Proxmox host on 28 October 2026; they must not be assumed present
by any later migration or installation scripts.

### Source checkout for review (no installation)

```bash
git -C /root/tobe4home-bootstrap pull --ff-only
bash /root/tobe4home-bootstrap/bootstrap/launch.sh
# Expected while not ready: explicit diagnostic and exit code 3.
```

The development branch is mutable. Wait for a tagged and verified installer
release before using any host-root provisioning command. No site-private
values or credentials may be committed to the public repository.

