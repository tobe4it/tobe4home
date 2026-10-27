#!/usr/bin/env python3
"""tobe4home stage-0 localhost-only, zero-dependency setup-plan wizard.

No credentials collected, no privileged operations and NO installation actions.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import collections
import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

DEFAULT_STATE = Path("/var/lib/tobe4home/site.local.json")
DEFAULT_PREFIX = os.environ.get("TOBE4HOME_CONTAINER_PREFIX", "tobe4home")
PREFIX_RE = re.compile(r"^[a-z]([a-z0-9-]*[a-z0-9])?$")

def normalized_prefix(raw: str) -> str:
    prefix = raw.strip().removesuffix("-")
    if not PREFIX_RE.fullmatch(prefix) or len(prefix) > 57:
        raise ValueError("Hostname prefix must be lowercase DNS-label characters, up to 57 characters.")
    return prefix

PHASES = (
    ("00", "Proxmox and network preflight", "Stage-0 LXC; SSH-only administration"),
    ("01", "Recovery bootstrap", "Git checkout, SSH, Ansible, local secrets, offline recovery"),
    ("02", "Recovery and backups", "Independent backup target and a verified restore"),
    ("03", "Internal Git and CI", "Forgejo LTS, isolated runners, protected changes"),
    ("04", "Identity and reverse proxy", "OIDC, TLS and per-user authorization"),
    ("05", "Local AI development", "Local LLM, isolated coding agent and tool gateway"),
    ("06", "Workflow services", "Langflow, MCP and selectable service blueprints"),
)
LABEL_RE = re.compile(r"^[\w .-]{2,64}$", flags=re.UNICODE)
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
TZ_RE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z_+-]+){1,3}$")
VALID_BACKUPS = {"nas", "external", "other", "not-configured"}

def validate(values: dict[str, str]) -> dict[str, str]:
    """Validate nonsecret bootstrap inputs. These are NOT deployment approvals."""
    result = {k: values.get(k, "").strip() for k in (
        "site_label", "base_domain", "timezone", "dns_resolver", "backup_kind")}
    result["container_prefix"] = normalized_prefix(values.get("container_prefix", DEFAULT_PREFIX))
    if not LABEL_RE.fullmatch(result["site_label"]):
        raise ValueError("Site label must be 2–64 letters, numbers, spaces, dot or hyphen.")
    if not DOMAIN_RE.fullmatch(result["base_domain"]):
        raise ValueError("Use a valid lowercase DNS domain, e.g. home.example.org.")
    if not TZ_RE.fullmatch(result["timezone"]):
        raise ValueError("Timezone must resemble Europe/Berlin.")
    try:
        ipaddress.ip_address(result["dns_resolver"])
    except ValueError as exc:
        raise ValueError("DNS resolver must be a valid IPv4 or IPv6 address.") from exc
    if result["backup_kind"] not in VALID_BACKUPS:
        raise ValueError("Select an available backup destination category.")
    return result

def save_plan(path: Path, plan: dict[str, str]) -> None:
    """Atomic owner-only file; never write secrets to the Git working tree."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".site.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"schema_version": 1, "site": plan, "deployment_enabled": False},
                      out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def load_plan(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate(data["site"])
    except (FileNotFoundError, ValueError, KeyError, TypeError, OSError):
        return {}

def render(plan: dict[str, str], csrf: str, error: str = "", saved: bool = False) -> str:
    def val(key: str) -> str:
        return html.escape(plan.get(key, ""), quote=True)
    def option(key: str, label: str) -> str:
        selected = " selected" if plan.get("backup_kind") == key else ""
        return f'<option value="{key}"{selected}>{html.escape(label)}</option>'
    rows = "".join(
        f"<li><strong>{n} · {html.escape(title)}</strong><span>{html.escape(desc)}</span></li>"
        for n, title, desc in PHASES)
    note = ('<p class="ok">Local draft saved. No services have been deployed.</p>' if saved
            else '<p class="error">' + html.escape(error) + '</p>' if error else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tobe4home – Setup</title>
<style>
:root{{font-family:system-ui,-apple-system,sans-serif;color-scheme:light dark}}
body{{max-width:880px;margin:35px auto;padding:0 18px;line-height:1.55}}
header{{border-bottom:1px solid #8886;margin-bottom:25px}}
form{{display:grid;gap:15px;padding:20px;border:1px solid #8886;border-radius:12px}}
label{{display:grid;gap:6px;font-weight:600}}
input,select,button{{font:inherit;padding:10px;border-radius:7px;border:1px solid #8888}}
button{{background:#2466aa;color:white;cursor:pointer;border:0;font-weight:700}}
small,li span{{color:gray}} li{{margin-bottom:12px}} li span{{display:block}}
.ok{{color:green}} .error{{color:crimson}}
</style></head><body>
<header><h1>tobe4home Setup</h1>
<p>Stage 0 – collect non-sensitive settings before deploying anything else.</p></header>
{note}
<form method="post" action="/save">
<input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}">
<label>Installation label <input name="site_label" maxlength="64" required value="{val('site_label')}" placeholder="Home Lab"></label>
<label>Container hostname prefix <input name="container_prefix" maxlength="58" required value="{val('container_prefix') or html.escape(DEFAULT_PREFIX,quote=True)}" placeholder="tobe4home-">
<small>Suggested: tobe4home-. Editable for all future guests; changing it does not rename this setup LXC. VMIDs are independent.</small></label>
<label>DNS base domain <input name="base_domain" maxlength="253" required value="{val('base_domain')}" placeholder="home.example.org"></label>
<label>Timezone <input name="timezone" maxlength="80" required value="{val('timezone') or 'Europe/Berlin'}"></label>
<label>DNS resolver IP <input name="dns_resolver" maxlength="45" required value="{val('dns_resolver')}" placeholder="192.0.2.53"></label>
<label>Independent backup destination <select name="backup_kind">
{option('not-configured', 'Not configured – must be resolved before production')}
{option('nas', 'NAS / network storage')}
{option('external', 'External storage')}
{option('other', 'Other independent backup system')}
</select></label>
<p><small>Do not enter passwords, API keys, private addresses belonging to another user,
or sensitive files. Values are saved only inside this LXC, mode 0600.
This wizard cannot create users, alter Proxmox, or deploy services.</small></p>
<button type="submit">Save draft installation plan</button>
</form>
<h2>Prerequisite installation path</h2>
<ol>{rows}</ol>
<p><strong>Next gate:</strong> restore testing, human approval and separate
Ansible implementations are required before write-capable deployments.</p>
</body></html>"""

def make_handler(state_path: Path, setup_code: str):
    """All endpoints require TLS-protected HTTP Basic authentication."""
    if len(setup_code) < 24:
        raise ValueError("Setup code is missing or too short")
    csrf = secrets.token_urlsafe(32)
    attempts: dict[str, collections.deque[float]] = {}
    attempt_lock = threading.Lock()
    failure_limit = 8
    failure_window_seconds = 300

    def authenticate(raw_header: str | None) -> bool:
        if not raw_header or not raw_header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(raw_header[6:].strip(), validate=True)
            username, password = raw.decode("utf-8").split(":", 1)
        except (ValueError, UnicodeError, binascii.Error):
            return False
        return secrets.compare_digest(username, "setup") and secrets.compare_digest(password, setup_code)


    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            body_bytes = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body_bytes)

        def _require_auth(self) -> bool:
            ip = self.client_address[0]
            now = time.monotonic()
            with attempt_lock:
                recent = attempts.setdefault(ip, collections.deque())
                while recent and now - recent[0] > failure_window_seconds:
                    recent.popleft()
                if len(recent) >= failure_limit:
                    self._reply(429, "Too many failed login attempts. Retry later.",
                                "text/plain; charset=utf-8")
                    return False
            if authenticate(self.headers.get("Authorization")):
                with attempt_lock:
                    attempts.pop(ip, None)
                return True
            with attempt_lock:
                attempts.setdefault(ip, collections.deque()).append(now)
            response = b"Setup login required"
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="tobe4home setup", charset="UTF-8"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return False

        def do_GET(self) -> None:
            if not self._require_auth():
                return
            if self.path == "/health":
                self._reply(200, "ok", "text/plain; charset=utf-8")
            elif self.path in ("/", "/saved"):
                self._reply(200, render(load_plan(state_path), csrf, saved=self.path == "/saved"))
            else:
                self._reply(404, "Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if not self._require_auth():
                return
            if self.path != "/save":
                return self._reply(404, "Not found", "text/plain; charset=utf-8")
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 1 or length > 16_384:
                return self._reply(413, "Invalid request size", "text/plain; charset=utf-8")
            params = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"),
                              keep_blank_values=True)
            if not secrets.compare_digest(params.get("csrf", [""])[0], csrf):
                return self._reply(403, "Invalid request token", "text/plain; charset=utf-8")
            values = {key: params.get(key, [""])[0] for key in (
                "site_label", "base_domain", "timezone", "dns_resolver", "backup_kind", "container_prefix")}
            try:
                plan = validate(values)
                save_plan(state_path, plan)
            except (ValueError, OSError) as exc:
                return self._reply(400, render(values, csrf, error=str(exc)))
            self.send_response(303)
            self.send_header("Location", "/saved")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    return Handler

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--setup-code-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    if args.listen != "0.0.0.0":
        parser.error("Direct internal HTTPS mode listens on the guest's IPv4 interfaces.")
    setup_code = args.setup_code_file.read_text(encoding="ascii").strip()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(args.tls_cert), str(args.tls_key))
    server = ThreadingHTTPServer((args.listen, args.port),
                                 make_handler(args.state_file, setup_code))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
