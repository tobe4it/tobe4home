# ADR 001 – One persistent controller, no mandatory Stage-0 LXC

Status: **architecture decision / proposed implementation target** (27 October 2026). This decision changes the future clean-install topology; it has **not** migrated the existing test installation.

**UI selection:** [ADR 002 – AnsibleForms 7](ADR-002-ANSIBLEFORMS-UI.md)
is the accepted frontend for this controller. A small deterministic
Proxmox-topology planner remains our own backend; AnsibleForms supplies
forms, workflow approval and job output. No dedicated custom full UI.

> **Current implementation note (30 October 2026).** The architecture has
> been reduced to the sole unprivileged CT1001: the older description of a
> running CT1000 stage and the selection of AnsibleForms as the primary
> user interface are **historical**, not current operating instructions.
> [ADR-003](ADR-003-LLM-CHAT-FIRST-PLATFORM.md) makes the LLM chat the
> primary tobe4home UI, with AnsibleForms as its background workflow
> engine. The chat UI is not implemented in the current bootstrap.
> See [safe rebootstrap gates](REBOOTSTRAP-CHAT-FIRST.md) before considering
> deletion and replacement of the functioning CT1001.
>
## Context

The stage-0 prototype currently provisions `CT 1000 (tb4h-setup)` with a small HTTPS form. It then provisions `CT 1001 (tb4h-ansible)` via an explicit host-side script. Keeping both as permanent control-plane services duplicates wizard, configuration, maintenance, credentials and recovery concerns.

The operator wants an unattended deployment of the **approved** baseline infrastructure, followed by a graphical prompt→Ansible→Git→CI→deployment experience.

## Decision

**CT 1001 is the only mandatory persistent tobe4home controller.** Its responsibilities are:

- Authenticated internal web UI: infrastructure parameters, detected facts, conditional service choices, graphical plan/diff, approval, job progress, failures and resume.
- **Deterministic** infrastructure plan compiler (not an LLM-generated shell script) using validated site inputs, read-only hypervisor inventory, hardware capacity, network/bridge/Storage/template availability, isolation requirements and chosen operating modes.
- A narrow provisioning/job-execution interface backed by separate credentials and explicitly allowlisted operations. Neither the web-service account nor a coding agent gets unconditional hypervisor-root access.
- Ansible runtime: pinned, supported Ansible version, versioned base roles, secrets outside Git, check/lint/test/healthcheck and bounded deployment against the exact approved plan.
- A prompt/blueprint catalogue; a sandboxed coding agent may generate Ansible changes in a reviewed Git branch/PR **only**. Its output never bypasses CI and operator approval for later platform changes.

**Stage-0 terminal bootstrap** collects *only* the essential parameters needed to create and reach CT 1001 (Proxmox target, storage, network, VMID selection, DNS, credentials for first login and initial safe SSH/TLS access). It validates and creates the unprivileged Rocky-Linux CT, installs the supported controller prerequisites, starts the web app, reports its URL and then **exits**. No long-running shell process waiting for browser interaction.

**Controller web onboarding** collects remaining values: existing vs newly installed Git, coding-agent mode, existing vs new model endpoint, desired CI isolation, host capacity, intended service catalogue and recovery/backup policy. It runs read-only discovery and **graphically selects and reviews** a minimal infrastructure topology **inside CT 1001, before deploying CT 1002+**.

The planning component is a separate, testable module/service **inside CT 1001**. Ansible does not determine business requirements; Ansible applies the approved, declarative plan.

After explicit approval of a fingerprinted immutable plan revision, a permission-scoped controller may deploy the exact approved guests in dependency order, with health checks and persisted state. Routine steps within that **same approval** do not require repeated prompts. Changing the target VMIDs, networks, storage, privilege scope, images or additional services invalidates approval and requires a new plan review.

## Conditional infrastructure topology

| Function | New guest needed if | Can avoid new guest if |
| --- | --- | --- |
| Git/Forgejo | independent local GitOps service required | approved existing Git service is chosen |
| Coding agent | isolated local prompt-to-Ansible code generation selected | an approved existing isolated agent service is integrated |
| Model inference | local inference selected, no compatible endpoint available | existing authorized model API is configured |
| CI runner | separate isolation/runtime capacity required | authorized isolated runner already exists |

VMIDs `1002–1004` are **not** fixed service IDs; allocate after cluster-wide inventory and resource validation. For hardware/SELinux/GPU constraints, a VM may be more appropriate than an LXC. Never allocate guests simply because a number is free. Failure resumes from persisted task state; it never destroys an unrelated pre-existing guest.

The UI and Ansible execution can live within the **same CT**, but must run as isolated users/services with a restricted job gateway and separate credentials. The code-generating agent must remain outside the privileged controller execution context.

## Current test-installation transition

The existing real-test estate is intentionally not destroyed:
- `CT 1000` remains temporarily the running setup UI and holds `site.local.json`.
- `CT 1001` already exists, with Rocky Linux 10, `ansible-core 2.16.16` installed, a successful `ansible localhost -c local -m ansible.builtin.ping`, and an active SSH daemon. Upstream Ansible Core 2.16 is EOL; a supported pinned runtime remains a release gate.
- Implement the controller UI/plan compiler and safe import of the site configuration from CT 1000. Verify values and permissions, then transfer the UI endpoint/hostname and confirm access.
- **Only after operator approval and successful post-migration checks** may CT 1000 be decommissioned. Do not silently destroy it or re-create CT 1001.

## Deliverables (none claimed delivered by this decision)

1. Adapt Stage-0 bootstrap / whiptail to target **CT 1001 directly** for fresh installations.
2. Install authenticated HTTPS web UI with site-local state within CT 1001; implement migration/import for existing CT 1000 data.
3. Read-only Proxmox API discovery and user-selectable operating modes; graphically render explainable dependency/resource plans, with tests.
4. Implement immutable plan version + explicit approval gates + minimal permission-scoped executor and resumable job status.
5. Implement Ansible provisioning roles to install only approved dependent Git/agent/model/CI services.
6. Implement optional recovery/export/restore independently from the main new-installation path.
7. Add unit/integration/negative tests; prove new installations, upgrades, partial failures, idempotence and identity/secret boundaries.

**Acceptance criterion:** for fresh installs, an operator runs one host-side bootstrap, uses only the CT 1001 web UI thereafter, approves one exact baseline topology, watches deployment of the approved infrastructure, and then builds future services using editable prompts with independent per-change approval.
