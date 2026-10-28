# ADR-002 – Provisioning guests from the permanent CT1001 controller

Status: **Design approved in principle; NOT implemented, NOT live-tested.**
Relates to ADR-001 (single controller). Do not interpret a green
onboarding preview as Proxmox provisioning readiness.

## Decision

tobe4home has exactly one permanent control-plane LXC on Proxmox:
unprivileged Rocky Linux 10 CT1001 (\`tb4h-controller\`). Users interact with
the German tobe4home onboarding UI running in AnsibleForms 7.4.2.
Its native Ansible RTE executes read-only discovery and, **only after
separate explicit approval**, deployment orchestration for new Proxmox LXC/VM
guests. OpenTofu generates resource plans; Ansible configures the created
guests. The controller is never itself used as a destructive test target.

No CT1000 stage, no privileged controller, no direct Proxmox root credentials
inside AnsibleForms.

## Current verified boundary

- The **bootstrap itself** is a Proxmox-host-side, root-approved installer.
  After \`INSTALL 1001\`, it creates only CT1001.
- The current onboarding form runs a non-mutating localhost playbook on the
  AnsibleForms RTE, and displays only a privacy-minimized, point-in-time
  Proxmox LXC/VM count collected earlier by the host-side bootstrap.
- This read-only host snapshot is *not* a Proxmox API connection from CT1001.
  It gives CT1001 **no** permissions to create, stop or delete guests.
- **Not yet implemented:** PVE token lifecycle, least-privilege rights,
  OpenTofu provisioner, resource allocator, encrypted site configuration,
  signed/approved plan, Ansible guest installation, rollback/audit and
  live integration tests.

## Provisioning trust boundaries (target)

1. **Discovery:** a separate read-only API token constrained to necessary
   Proxmox resources; no login password, SSH root key or Proxmox host shell.
   Check accessible node, template, storage, bridge, existing guests, ID
   collisions and quotas. Inventory must be validated and periodically
   refreshed. A stale inventory never authorizes a mutation.
2. **Planning:** server-side form selections -> constrained schema ->
   OpenTofu plan. The proposed VMIDs (reserved test range starting 1002),
   storage volume, network bridge, template digest, CPU, RAM, network ACL,
   backup policy and host are explicit. Existing guest IDs, especially
   CT1001 and non-tobe4home guests, are excluded by policy.
3. **Authorization:** show a human-readable exact change list with a
   content digest; require fresh one-time explicit approval per plan.
   Reject plan drift, expired discovery, changed targets, additional
   resources, unknown provider operations, replacement or destroy actions.
4. **Execution:** a separate privilege-separated Proxmox API token, only
   after admin provisioning, with the smallest Proxmox ACLs required for
   the approved operations and target resources. API token privilege
   separation must be enabled; the backing account cannot carry broader
   rights than intended. Do not assign \`Administrator\`, \`PVEAdmin\`,
   unconditional \`root@pam\`, or broad \`/vms\` write ACL by default.
   Which permissions are required for *creating new guests* (VM.Allocate,
   Datastore.AllocateSpace, SDN/bridge use, template and VM.Config.*
   capabilities) must be tested against the actual PVE release and
   constrained storage/node/VMID allocation design. Where PVE ACL granularity
   cannot enforce the intended restrictions, use an independent,
   auditable allowlist execution gateway instead of widening the API token.
5. **Configuring guests:** Ansible uses a newly provisioned, scoped
   management identity. The RTE must not use the existing family/legacy
   guests' credentials automatically. Only configure guests whose
   identity/ownership was independently checked.
6. **Completion:** show exact per-task Ansible durations, health checks,
   guest inventories, audit log and an immutable deployment receipt.
   Recover safely from partial provisioning; never silently destroy an
   existing guest on retry.
7. **Secrets:** collect the API token in the controller's approved secret
   store under least-privilege access, mask logs, never place secrets in
   form fields, repo YAML, ToFu plans, process arguments or URLs.
   Permission escalation and token creation must not occur in onboarding.

## Acceptance checklist

- [ ] Provision and inspect a dedicated, privilege-separated PVE API identity
      and verify it cannot affect CT1001 or any pre-existing guest.
- [ ] Controller-to-PVE read-only API access works with TLS certificate
      validation; no \`curl -k\` outside initial self-signed local health.
- [ ] Site-specific bridge/storage/template and new VMID allocation from
      actual PVE reads, no hard-coded assumptions.
- [ ] OpenTofu plan signed/hashed, reviewed and explicitly approved;
      must reject destroy/replace/changes outside tobe4home scope.
- [ ] Create one disposable test LXC and one VM, configure via Ansible,
      verify network, restart, access, backups and rollback.
- [ ] No mutation before approval or after snapshot/plan drift; test with
      unauthorised user, wrong token, existing VMID and unavailable storage.
- [ ] Full end-to-end test from new PVE install -> CT1001 -> GUI -> plan ->
      approval -> guests -> health and audit, including failure/recovery.
- [ ] Final UI clearly distinguishes *discovered* assets, *planned*
      changes, *deployed* assets and inherited/legacy guests.
- [ ] Detailed per-task execution duration report at the end.

Do not mark the bootstrap or UI as a turnkey platform until this checklist
passes with a live PVE acceptance environment.

## RTE file handling

AnsibleForms 7 supports \`RTE_FILES=transfer\` where the playbooks folder is
sent into a job-local directory. Native installer defaults may use
\`RTE_FILES=local\` with a shared folder. Never hardcode a native app path
in a playbook; refer to sidecar files through \`playbook_dir\`. The Proxmox
snapshot is published **before** the tobe4home preview playbook, with
validation, clear fail-closed error, and no privilege escalation.
