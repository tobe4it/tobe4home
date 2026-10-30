# Chat-MVP in CT1001

**Experimental, no provisioning, no full Chat-first bootstrap.** No reset of CT1001.

## Trust and scope

- A standalone non-root systemd service `tb4h-chat` on the existing unprivileged Rocky Linux 10 CT1001.
- The server binds **only `127.0.0.1:8765` inside CT1001**. It requires an authenticated SSH tunnel to the container; the webpage itself has no user-account system yet. **Never publish this port directly to a LAN/WAN or add an unprotected reverse proxy.**
- HTTPS OpenAI-compatible model API at `/v1/chat/completions`, with ordinary system certificate verification, no redirects, no inherited HTTP proxy. Plain HTTP is allowed only to literal `127.0.0.1` / `::1` in the *same controller*.
- An optional API key is loaded through systemd `LoadCredential` from a root-only file. It is never sent to the browser.
- Messages live in the browser session, not a database. **No Proxmox tools, SSH automation, Ansible execution or file-writing tools are exposed to the model.** A model answer is untrusted advisory prose, not an approved plan.

## Guarded deployment

On the Proxmox host after review of the Git branch, run the read-only preview:

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash /root/tobe4home-bootstrap/bootstrap/deploy-chat-mvp-1001.sh
```

After checking the exact CT1001-only plan, apply in a attended SSH terminal:

```bash
sudo bash /root/tobe4home-bootstrap/bootstrap/deploy-chat-mvp-1001.sh --apply
# type exactly CHAT 1001
```

This checks controller identity and AnsibleForms/RTE health, stages only reviewed Chat assets, and creates the `tb4h-chat` service user, files, configuration, and service. It preserves existing local model configuration and refuses unrecognized or modified application files. It does **not** stop/reset CT1001 or change other guests.

Check:

```bash
sudo pct exec 1001 -- systemctl is-active tb4h-chat
sudo pct exec 1001 -- curl -fsS http://127.0.0.1:8765/api/status
```

`"configured":false` is **expected** until you configure a model. Chat is not usable before this configuration.

## Model endpoint

The installer deliberately **does not guess or contact any LLM**. The operator must securely set `/etc/tobe4home/chat.json` **inside CT1001**, using a real authorized model API (the following is only an example):

```json
{"api_url":"https://llm.example.invalid/v1/chat/completions","model":"MODEL_NAME"}
```

An unencrypted API connection to another machine is refused. If a model requires a secret, write the token to the precreated root-only `/etc/tobe4home/llm-api-key` through an appropriately secured editor, **not a shell command containing the token**. The application receives it through systemd, not an environment variable. Restart only this new service after configuration:

```bash
sudo pct exec 1001 -- systemctl restart tb4h-chat
```

A model API must support the OpenAI-compatible text chat-completions JSON format. Model compatibility, TLS and response quality require a live acceptance test.

## Browser via authenticated tunnel

If CT1001 has a user `tb4h` with an approved SSH public key (created only if previously configured), run **from your own computer**:

```bash
ssh -N -L 8765:127.0.0.1:8765 tb4h@192.168.3.129
```

Then open `http://127.0.0.1:8765/` in that computer's browser. The SSH connection protects transport and authenticates the tunnel. If no authorized SSH user exists on CT1001, configure one securely first. **Do not replace loopback binding with 0.0.0.0.** The MVP uses a strict Host/Origin check and expects local port 8765.

The new Chat service **does not reuse AnsibleForms authentication** and is not accessible through the existing AnsibleForms HTTPS URL. An integrated, authenticated Chat-first web entrypoint is a later deliverable.

## Remaining gates

This MVP does **not** generate or persist Ansible playbooks, run CI/PR workflows, provision Proxmox guests, discover services inside existing LXC, or approve/execute changes. Those capabilities remain documented in [ADR-003](ADR-003-LLM-CHAT-FIRST-PLATFORM.md) and GitHub Issue #4. The safe reinstall decision and external backup gates remain in [REBOOTSTRAP-CHAT-FIRST](REBOOTSTRAP-CHAT-FIRST.md).

**Do not destroy the live CT1001 for this MVP.**
