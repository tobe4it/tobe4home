# ADR 002 – AnsibleForms 7 as tobe4home controller user interface
> **Produktpräzisierung (28.10.2026):** Die ursprünglich als primäre
> Bedienoberfläche vorgesehene AnsibleForms-Formularsammlung ist seit
> [ADR-003](ADR-003-LLM-CHAT-FIRST-PLATFORM.md) nur noch Workflow-/
> Ansible-Ausführungsschicht. Die primäre tobe4home-Oberfläche ist
> ein natürlicher LLM-Chat, der nach Prüfung und Freigabe Ansible-
> Artefakte generiert und bereitstellt. Die nativen AnsibleForms-
> Fähigkeiten bleiben wiederverwendet; dieser ältere UI-Entscheid
> ist insoweit überholt. Der Chat ist noch nicht implementiert.
>

Status: **accepted architectural choice, implementation pending** (27 October 2026).
Supersedes proposals to build a complete proprietary wizard UI or to make
Semaphore, AWX, Rundeck or ansible.ui the mandatory initial control plane.

## Decision

For future clean installations, the one mandatory controller guest
(`tb4h-controller`, nominally CT 1001) runs **AnsibleForms 7** as its
operator-facing web portal. The small initial Proxmox bootstrap remains a
terminal-based preflight/configuration menu; the full graphical onboarding,
infrastructure choices, plan review, approval and job logs are exposed through
AnsibleForms.

Official project: https://github.com/ansibleforms/ansibleforms
Documentation: https://ansibleforms.com/en/installation/
License: **GPL-3.0**, suitable for self-hosted use; keep project code separate
from AnsibleForms and evaluate distribution duties if integrating derivatives.

At the time of this decision, the latest upstream GitHub release is **7.4.2**
(published 27 October 2026). Deployment must use an explicitly reviewed,
pinned release/image digest, never floating `latest`, and check compatibility
of the matching runtime environment (RTE) image before enabling jobs.
Future upgrades require version review, backup and staged regression tests.

## What we reuse

- Form designer, dynamic field values and validation, multistep onboarding.
- Workflow rendering and explicit human approval nodes.
- Local/LDAP/OIDC identities, form-level roles, audit trail, job history,
  schedules, live output and API.
- Built-in Git synchronization for form definitions and Ansible projects.
- **Separated runtime environment (RTE)** that actually runs Ansible.
  The web-app image does *not* execute playbooks in version 7.

AnsibleForms runs an application, a relational database and one or more RTE
processes/containers. These need not become separate Proxmox LXCs: they can
reside within CT 1001 as isolated units provided runtime compatibility,
permissions, storage isolation and reliability tests pass.

## What remains a small tobe4home-specific component

`tb4h-planner`: a deterministic and testable read-only Proxmox inventory and
conditional-topology compiler, accessed by AnsibleForms via supported APIs.
It decides **what infrastructure is required**, based on user choices,
available existing services, storage, networks, supported guests,
VMID availability, CPU/RAM/GPU limits and dependency/security constraints.
AnsibleForms displays its plan, rationale, topology, affected VMIDs,
resource limits and intended operations.

The LLM does not choose unrestricted hypervisor actions, and Ansible itself
does not decide business needs. A separate permission-scoped execution
gateway, not the web-server identity or the coding agent, enforces
**immutable approved plan** scope and idempotent/resumable task status.
Prompt-generated Ansible requires a distinct change review and deployment
approval. A workflow diagram alone does not supply the required
Proxmox host/LXC network-and-dependency topology: that visualization is
an adapter/extension task, not an existing AnsibleForms capability.

## Runtime selection for Rocky Linux 10 unprivileged LXC

Preferred: **Podman** deployment using official AnsibleForms application,
database and RTE images (matching pinned version) with service management
and persistent volumes. The official installer supports Podman, Docker,
Kubernetes and native/systemd installation.

**Do not assume rootless Podman works nested in an unprivileged Proxmox LXC.**
Check user namespace/subuid mapping, cgroup v2, networking, rootless storage,
SELinux and service startup on CT 1001 in a read-only preflight. Do not enable
nesting, privileged containers, host socket access or broad capabilities
as an automatic workaround. If the required isolation is unsupported,
consider the officially supported **native/systemd Rocky Linux installation**
or an explicitly approved isolated VM. Preserve the existing CT 1001
state and Ansible package installation pending the decision.

Upstream 7.x does not run using the system `ansible-core 2.16.16`
currently installed on CT 1001: its RTE is a distinct component. Confirm
the RTE's supported Ansible/Python lifecycle and collection pins.
No unreviewed `curl | sh` remote installer as Proxmox root. Inspect/pin
installation source before executing and avoid overwriting site-local files.

## Initial implementation gates

1. Read-only CT 1001 compatibility preflight and resource budget;
   verify AnsibleForms application + database + RTE requirements.
2. Operator-approved, pinned installation within CT 1001, HTTPS, backup
   of form state and database, health checks; avoid interrupting SSH.
3. Minimal AnsibleForms self-service form `tobe4home – Infrastruktur`
   with site-local values and guarded immutable choices.
4. Independent read-only `tb4h-planner` API with local mock inventories,
   negative tests for existing guests, VMID conflicts and out-of-scope
   resources, then live Proxmox discovery with dedicated read scope.
5. Render/approve a topological plan with memory, storage, network,
   ownership and dependency constraints. **Approval is bounded by
   the plan revision** and may be revoked before job start.
6. Wire the approved plan to narrow executor and Ansible RTE. Prove
   recovery from failed provisioning before adding Git/agent/model guests.
7. Safely migrate existing CT 1000 site's private wizard data,
   authenticate in CT 1001 web UI and verify parity before optional
   retirement of CT 1000; no automatic deletion.

**Acceptance:** One host-side bootstrap creates CT 1001 on a new host;
then AnsibleForms on CT 1001 carries out planning, approval,
deployment and verification of only the required infrastructure.
