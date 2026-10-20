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

This repository is being populated from reviewed, completed infrastructure components. Until component migration and validation are complete, treat the published material as a development release rather than a turnkey installation.

## Documentation

English and German setup and operations documentation is available under `docs/` and `docs/handbook/`. A newcomer path starts with infrastructure prerequisites and basic security; advanced integrations are optional.

