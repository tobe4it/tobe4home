#!/usr/bin/env python3
"""tobe4home HTTPS bootstrap wizard: config -> guest discovery -> plan.

No privileged operations, no implicit deployment and no secret collection.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import collections
import html
import hashlib
import io
import zipfile
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
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
    ("00", "Proxmox und Netzwerk", "Stage-0-LXC mit internem HTTPS-Zugang"),
    ("01", "Wiederherstellbarer Bootstrap", "Git, SSH, Ansible und unabhängige Recovery"),
    ("02", "Backup und Wiederherstellung", "Unabhängiges Backup-Ziel und geprüfter Restore"),
    ("03", "Interne Git-Plattform", "Forgejo LTS und isolierte CI-Runner"),
    ("04", "Identität und Reverse-Proxy", "OIDC, TLS und Benutzerberechtigungen"),
    ("05", "Lokale KI-Entwicklung", "LLM, isolierte Coding-Agenten und Tool-Gateway"),
    ("06", "Workflows und weitere Dienste", "Langflow, MCP und wählbare Dienstvorlagen"),
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

def usable_dns_address(raw: str) -> str:
    """Reject loopback resolvers, unsupported special IPs and invalid text."""
    try:
        address = ipaddress.ip_address(raw.strip().strip(",;"))
    except ValueError:
        return ""
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
        return ""
    return str(address)


def parse_resolv_conf(raw: str) -> list[str]:
    """Read effective nameservers only; no assumptions about their origin."""
    found = []
    for line in raw.splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        parts = line.split()
        if len(parts) != 2 or parts[0] != "nameserver":
            continue
        ip = usable_dns_address(parts[1])
        if ip and ip not in found:
            found.append(ip)
    return found


def parse_dhcp_dns(raw: str) -> list[str]:
    """Recognize NetworkManager DHCP option 6, not arbitrary IP4.DNS values."""
    found = []
    for line in raw.splitlines():
        match = re.search(r"(?:^|\s)domain_name_servers\s*=\s*(.+)$", line)
        if not match:
            continue
        for token in re.split(r"[,\s]+", match.group(1).strip()):
            ip = usable_dns_address(token)
            if ip and ip not in found:
                found.append(ip)
    return found


def detect_network_dns() -> dict[str, str]:
    """Offer a best-effort, read-only DNS suggestion from the running guest.

    On Proxmox, resolv.conf may be supplied by the host even when the LXC
    address comes from DHCP; never label it DHCP without actual lease data.
    """
    dhcp = []
    try:
        result = subprocess.run(
            ["nmcli", "--fields", "DHCP4.OPTION", "device", "show", "eth0"],
            capture_output=True, text=True, timeout=3, check=False)
        if result.returncode == 0:
            dhcp = parse_dhcp_dns(result.stdout)
    except (OSError, subprocess.TimeoutExpired):
        pass
    effective = []
    try:
        effective = parse_resolv_conf(
            Path("/etc/resolv.conf").read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        pass
    if dhcp:
        warning = ""
        if effective and dhcp[0] not in effective:
            warning = ("Achtung: Der über DHCP angebotene DNS steht nicht in "
                       "/etc/resolv.conf. Proxmox könnte andere DNS-Werte vorgeben.")
        return {"value": dhcp[0], "source": "DHCP-Option 6 (eth0)",
                "warning": warning}
    if effective:
        return {"value": effective[0],
                "source": "/etc/resolv.conf (DHCP-Herkunft nicht bestätigt)",
                "warning": ""}
    return {"value": "", "source": "Kein DNS-Server automatisch ermittelbar",
            "warning": "Bitte den internen DNS-Server manuell eintragen."}


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

def render(plan: dict[str, str], csrf: str, error: str = "", saved: bool = False,
           dns_suggestion: dict[str, str] | None = None) -> str:
    def val(key: str) -> str:
        return html.escape(plan.get(key, ""), quote=True)
    dns_suggestion = dns_suggestion or {"value": "", "source": "Nicht ermittelt", "warning": ""}
    dns_value = plan["dns_resolver"] if "dns_resolver" in plan else dns_suggestion["value"]
    dns_description = html.escape(dns_suggestion["source"])
    dns_warning = html.escape(dns_suggestion["warning"])
    def option(key: str, label: str) -> str:
        selected = " selected" if plan.get("backup_kind") == key else ""
        return f'<option value="{key}"{selected}>{html.escape(label)}</option>'
    rows = "".join(
        f"<li><strong>{html.escape(title)}</strong><span>{html.escape(desc)}</span></li>"
        for _n, title, desc in PHASES)
    note = ('<p class="ok">Konfiguration gespeichert. Weiter mit der Bestandsaufnahme.</p>' if saved
            else '<p class="error">' + html.escape(error) + '</p>' if error else "")
    navigation = ('<nav aria-label="Installationsschritte"><strong>1. Einstellungen</strong> '
                  '<a href="/discovery">2. Bestandsaufnahme</a> '
                  '<a href="/plan">3. Installationsplan</a>'
           '<a href="/recovery">Werkzeuge: Recovery-Export</a></nav>'
                  if plan and not error else
                  '<nav aria-label="Installationsschritte"><strong>1. Einstellungen</strong>'
                  '<span>2. Bestandsaufnahme</span><span>3. Installationsplan</span></nav>')
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tobe4home – Setup</title>
<style>
:root{{font-family:system-ui,-apple-system,sans-serif;color-scheme:light dark}}
body{{max-width:880px;margin:35px auto;padding:0 18px;line-height:1.55}}
nav{{display:flex;flex-wrap:wrap;gap:16px;margin:18px 0;padding:14px;border:1px solid #8886;border-radius:8px}}
a{{color:#3782dd}}
header{{border-bottom:1px solid #8886;margin-bottom:25px}}
form{{display:grid;gap:15px;padding:20px;border:1px solid #8886;border-radius:12px}}
label{{display:grid;gap:6px;font-weight:600}}
input,select,button{{font:inherit;padding:10px;border-radius:7px;border:1px solid #8888}}
button{{background:#2466aa;color:white;cursor:pointer;border:0;font-weight:700}}
small,li span{{color:gray}} li{{margin-bottom:12px}} li span{{display:block}}
.ok{{color:green}} .error{{color:crimson}}
</style></head><body>
<header><h1>tobe4home Setup</h1>
<p>Schritt 1 von 3 – Einstellungen erfassen. Keine Installation ohne gesonderte Freigabe.</p></header>
{navigation}
{note}
<form method="post" action="/save">
<input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}">
<label>Installationsname <input name="site_label" maxlength="64" required value="{val('site_label')}" placeholder="Home Lab"></label>
<label>Container-Namenspräfix <input name="container_prefix" maxlength="58" required value="{val('container_prefix') or html.escape(DEFAULT_PREFIX,quote=True)}" placeholder="tobe4home-">
<small>Der Präfix gilt für zukünftige Gäste; dieser Setup-Container wird nicht umbenannt.</small></label>
<label>DNS-Basisdomäne <input name="base_domain" maxlength="253" required value="{val('base_domain')}" placeholder="home.example.org"></label>
<label>Zeitzone <input name="timezone" maxlength="80" required value="{val('timezone') or 'Europe/Berlin'}"></label>
<label>DNS-Resolver (IPv4/IPv6) <input name="dns_resolver" maxlength="45" required value="{html.escape(dns_value, quote=True)}" placeholder="Interne DNS-IP">
<small>Automatische Erkennung: {dns_description}. Du kannst den vorgeschlagenen Wert überschreiben.</small>
{f'<small role="alert">{dns_warning}</small>' if dns_warning else ''}</label>
<label>Geplanter Backup-Zieltyp <select name="backup_kind">
{option('not-configured', 'Noch nicht ausgewählt – vor Produktivbetrieb erforderlich')}
{option('nas', 'NAS / Netzwerkspeicher')}
{option('external', 'Externer Datenträger')}
{option('other', 'Anderes unabhängiges Backup-System')}
</select></label>
<p><small>Keine Passwörter oder API-Schlüssel eintragen. Die Konfiguration bleibt lokal
in diesem Container (Dateirechte 0600). Die WebApp ändert noch keine weiteren Dienste.</small></p>
<button type="submit">Speichern und weiter zur Bestandsaufnahme</button>
</form>
<h2>Vorgesehene Ausbauphasen</h2>
<ol>{rows}</ol>
<p><strong>Hinweis:</strong> Weitere Dienste werden erst durch gesondert
geprüfte Ansible-Implementierungen und explizite Freigaben bereitgestellt.</p>
</body></html>"""


def discover_guest() -> dict[str, str]:
    """Read-only guest inventory; never implies Proxmox host access."""
    import socket
    result = {"hostname": socket.gethostname(), "os": "Unbekannt",
              "guest_ipv4": "Nicht ermittelt", "dns": "Nicht ermittelt",
              "dns_origin": "Nicht ermittelt"}
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8")
        match = re.search(r'^PRETTY_NAME="?([^"\n]+)"?$', os_release, re.MULTILINE)
        if match:
            result["os"] = match.group(1)
    except (OSError, UnicodeError):
        pass
    try:
        query = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", "eth0"],
                               capture_output=True, text=True, timeout=3, check=False)
        if query.returncode == 0:
            for match in re.finditer(r"\binet (\d{1,3}(?:\.\d{1,3}){3})/", query.stdout):
                try:
                    result["guest_ipv4"] = str(ipaddress.IPv4Address(match.group(1)))
                    break
                except ValueError:
                    continue
    except (OSError, subprocess.TimeoutExpired):
        pass
    dns = detect_network_dns()
    result["dns"] = dns["value"] or "Nicht ermittelt"
    result["dns_origin"] = dns["source"]
    return result


def flow_page(title: str, step: int, content: str) -> str:
    """All supplied dynamic values in content must be html-escaped first."""
    nav = ('<nav aria-label="Installationsschritte">'
           '<a href="/">1. Einstellungen</a>'
           '<a href="/discovery">2. Bestandsaufnahme</a>'
           '<a href="/plan">3. Installationsplan</a></nav>')
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>tobe4home – {html.escape(title)}</title>
<style>
:root{{font-family:system-ui,-apple-system,sans-serif;color-scheme:light dark}}
body{{max-width:860px;margin:36px auto;padding:0 18px;line-height:1.55}}
nav{{display:flex;flex-wrap:wrap;gap:18px;padding:16px;margin:20px 0;border:1px solid #8885;border-radius:8px}}
a{{color:#3782dd}}
section{{border:1px solid #8885;border-radius:9px;padding:18px;margin:18px 0}}
dl{{display:grid;grid-template-columns:minmax(130px,1fr) 2fr;gap:9px}}
dt{{font-weight:600}} dd{{margin:0;overflow-wrap:anywhere}}
.button{{display:inline-block;border:0;border-radius:7px;background:#2466aa;color:white;padding:11px 18px;text-decoration:none}}
small{{color:gray}}
</style></head><body>
<header><h1>tobe4home – {html.escape(title)}</h1>
<p>Schritt {step} – Geführte Einrichtung, ohne automatische Änderungen am Hypervisor.</p></header>
{nav}
{content}
</body></html>"""


def render_discovery(plan: dict[str, str], facts: dict[str, str]) -> str:
    """A real, read-only inventory of the guest, not the Proxmox host."""
    def esc(value: str) -> str:
        return html.escape(value, quote=True)
    items = (
        ("Container-Hostname", facts["hostname"]),
        ("Betriebssystem", facts["os"]),
        ("IPv4 auf eth0", facts["guest_ipv4"]),
        ("Aktueller DNS", facts["dns"]),
        ("DNS-Herkunft", facts["dns_origin"]),
        ("Geplante Basisdomäne", plan["base_domain"]),
    )
    rows = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k,v in items)
    content = (f"<section><h2>Erkannte Umgebung</h2><dl>{rows}</dl></section>"
               '<p><strong>Grenze der Erkennung:</strong> Diese WebApp kann '
               'aktuell nur Informationen innerhalb ihres LXC lesen. '
               'Proxmox-Cluster, NAS und andere Hosts wurden nicht inventarisiert.</p>'
               '<p><a href="/">Zurück zu den Einstellungen</a> · '
               '<a class="button" href="/plan">Weiter zum Installationsplan</a></p>')
    return flow_page("Bestandsaufnahme", 2, content)


def recovery_bundle(plan: dict[str, str]) -> bytes:
    """Portable Stage-1 recovery starter: one explicit operator export."""
    validated = validate(plan)
    site = {"schema_version": 1, "site": validated,
            "deployment_enabled": False}
    files = {
        "site/site.local.json": (
            json.dumps(site, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "ansible/inventory.yml": (
            "all:\n  hosts:\n    setup-local:\n      ansible_connection: local\n"
            "      ansible_python_interpreter: /usr/bin/python3\n"
        ).encode("utf-8"),
        "ansible/ansible.cfg": (
            "[defaults]\ninventory = inventory.yml\n"
            "retry_files_enabled = False\nhost_key_checking = True\n"
        ).encode("utf-8"),
        "ansible/playbooks/verify-local.yml": (
            "---\n- name: Verify isolated local recovery runner\n"
            "  hosts: setup-local\n  gather_facts: false\n  tasks:\n"
            "    - name: Confirm local-only connection\n"
            "      ansible.builtin.assert:\n        that:\n"
            "          - ansible_connection == 'local'\n"
            "        fail_msg: 'This starter playbook must run locally.'\n"
        ).encode("utf-8"),
        "README-RECOVERY.md": (
            "# tobe4home – Recovery-Starterpaket (Entwicklungsstand)\n\n"
            "Dieses Paket ist der erste exportierbare Recovery-Schritt.\n"
            "Es enthält die lokal gespeicherte Site-Konfiguration,\n"
            "ein sicheres Ansible-Lokalbeispiel und SHA-256-Prüfsummen.\n\n"
            "## Nach dem Download (isolierter Testrechner)\n\n"
            "1. ZIP in einen neuen, isolierten Ordner entpacken.\n"
            "2. Befehl: python3 verify-recovery.py\n"
            "3. Falls Ansible installiert ist: cd ansible\n"
            "   und ansible-playbook playbooks/verify-local.yml\n"
            "4. Site-Parameter kontrollieren, keine produktiven Deployments.\n\n"
            "Grenzen: Kein NAS-Backup, kein VM-/LXC-Restore, keine\n"
            "Proxmox-API-Zugangsdaten, keine privaten SSH-Schlüssel.\n"
            "Die Auswahl NAS ist noch kein konfiguriertes Backupziel.\n"
        ).encode("utf-8"),
    }
    checksums = "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
        for name in sorted(files)
    )
    files["SHA256SUMS"] = checksums.encode("ascii")
    files["verify-recovery.py"] = (
        "from pathlib import Path\nimport hashlib\n"
        "root = Path(__file__).resolve().parent\n"
        "for line in (root / 'SHA256SUMS').read_text().splitlines():\n"
        "    expected, relative = line.split('  ', 1)\n"
        "    candidate = (root / relative).resolve()\n"
        "    if not candidate.is_relative_to(root) or not candidate.is_file():\n"
        "        raise SystemExit('FAIL: missing or unsafe recovery file')\n"
        "    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:\n"
        "        raise SystemExit('FAIL: recovery checksum mismatch')\n"
        "print('PASS: recovery starter files verified')\n"
    ).encode("utf-8")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, data in sorted(files.items()):
            item = zipfile.ZipInfo(filename, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o600 << 16)
            archive.writestr(item, data)
    payload = stream.getvalue()
    if len(payload) > 256_000:
        raise ValueError("Recovery export exceeds stage-1 size limit")
    return payload


def render_recovery(plan: dict[str, str], csrf: str) -> str:
    name = html.escape(plan["site_label"], quote=True)
    content = (
        '<section><h2>Optionales Werkzeug – Recovery-Grundlage exportieren</h2>'
        f'<p>Konfiguration: <strong>{name}</strong>. '
        'Erzeuge ein eigenständiges ZIP mit Einstellungen, '
        'Ansible-Grundgerüst, Prüfsummen und einer Anleitung '
        'für einen isolierten Wiederherstellungstest.</p>'
        '<p><strong>Tatsächliche Aktion:</strong> Die WebApp erzeugt '
        'das Paket erst nach Freigabe im Arbeitsspeicher und '
        'bietet es zum Download an. Keine Installation auf '
        'Proxmox, kein NAS-Zugriff, keine Änderung bestehender Dienste.</p>'
        '<p>Das ZIP enthält interne Konfigurationswerte. Sicher aufbewahren.</p>'
        '<form method="post" action="/recovery/export">'
        f'<input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}">'
        '<button type="submit" name="confirm" value="export-stage1">'
        'Recovery-Starterpaket erstellen und herunterladen</button></form>'
        '</section>'
        '<p><a href="/plan">Zurück zum Installationsplan</a></p>'
    )
    return flow_page("Recovery-Bootstrap", 4, content)


def render_plan(plan: dict[str, str]) -> str:
    """Reviewable next actions; never pretend write-capable modules exist."""
    headings = {
        "site_label": "Installationsname", "container_prefix": "Namenspräfix",
        "base_domain": "DNS-Basisdomäne", "timezone": "Zeitzone",
        "dns_resolver": "Vorgeschlagener DNS-Resolver",
        "backup_kind": "Backup-Zieltyp (ungeprüfte Betreiberangabe)",
    }
    rows = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(plan.get(field,''))}</dd>"
        for field,label in headings.items()
    )
    phases = (
        ("Stage 0", "Setup-Container und interner HTTPS-Zugriff", "Erfolgt"),
        ("Stage 1", "Ansible-Controller und notwendigen Git-/Agent-Betrieb bereitstellen",
         "Provisioner fehlt noch"),
        ("Stage 2", "Anpassbare Prompts in geprüfte Ansible-Projekte übersetzen",
         "Prompt-/Git-/CI-Pipeline fehlt noch"),
        ("Stage 3", "Freigegebene Ansible-Deployments und Backups/Restore",
         "Deployment-/Backup-Gates fehlen noch"),
    )
    stages = "".join(
        f"<li><strong>{html.escape(name)}:</strong> {html.escape(desc)} "
        f"<small>({html.escape(status)})</small></li>"
        for name, desc, status in phases)
    content = (
        f"<section><h2>Gespeicherte Konfiguration</h2><dl>{rows}</dl></section>"
        f"<section><h2>Installationsreihenfolge</h2><ol>{stages}</ol></section>"
        "<section><h2>Benötigte Installationsgrundlage</h2>"
        "<p>Bevor die eigentlichen tobe4home-Dienste aus Prompts entstehen, "
        "muss der Setup-Assistent die notwendige Steuerungsumgebung anlegen: "
        "Ansible-Controller, ein Git-Repository (neu oder vorhanden), "
        "eine isolierte Coding-Agent-Umgebung und einen Modell-Endpunkt "
        "(neu oder vorhanden). Der LXC-/VM-Bedarf wird erst nach "
        "Bestandsprüfung und Betriebsartauswahl verbindlich festgelegt.</p>"
        "<p><strong>Derzeit blockiert:</strong> Die Erstellung weiterer LXCs "
        "ist in diesem Entwicklungsstand noch nicht implementiert. "
        "Es wurde kein zusätzlicher Container angelegt.</p></section>"
        "<p><strong>Freigabestatus:</strong> Keine Infrastruktur-Provisionierung "
        "freigegeben oder gestartet. Es gibt noch keinen eingeschränkt "
        "berechtigten Proxmox-Executor. Ein Recovery-ZIP kann die "
        "Neuinstallation nicht ersetzen.</p>"
        '<p><a href="/discovery">Zurück zur Bestandsaufnahme</a> · '
        '<a href="/recovery">Werkzeug: Recovery-Export (optional)</a></p>'
    )
    return flow_page("Installationsplan", 3, content)


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
                self._reply(200, render(load_plan(state_path), csrf,
                                        saved=self.path == "/saved",
                                        dns_suggestion=detect_network_dns()))
            elif self.path in ("/discovery", "/plan", "/recovery"):
                current_plan = load_plan(state_path)
                if not current_plan:
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                if self.path == "/discovery":
                    self._reply(200, render_discovery(current_plan, discover_guest()))
                elif self.path == "/plan":
                    self._reply(200, render_plan(current_plan))
                else:
                    self._reply(200, render_recovery(current_plan, csrf))
            else:
                self._reply(404, "Not found", "text/plain; charset=utf-8")

        def do_POST(self) -> None:
            if not self._require_auth():
                return
            if self.path not in ("/save", "/recovery/export"):
                return self._reply(404, "Not found", "text/plain; charset=utf-8")
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 1 or length > 16_384:
                return self._reply(413, "Invalid request size", "text/plain; charset=utf-8")
            params = parse_qs(self.rfile.read(length).decode("utf-8", errors="replace"),
                              keep_blank_values=True)
            if not secrets.compare_digest(params.get("csrf", [""])[0], csrf):
                return self._reply(403, "Invalid request token", "text/plain; charset=utf-8")
            if self.path == "/recovery/export":
                if params.get("confirm", [""])[0] != "export-stage1":
                    return self._reply(403, "Explicit export approval missing",
                                       "text/plain; charset=utf-8")
                existing = load_plan(state_path)
                if not existing:
                    return self._reply(409, "Save site configuration first",
                                       "text/plain; charset=utf-8")
                try:
                    bundle = recovery_bundle(existing)
                except (ValueError, OSError):
                    return self._reply(500, "Recovery export failed",
                                       "text/plain; charset=utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 'attachment; filename="tobe4home-stage1-recovery.zip"')
                self.send_header("Content-Length", str(len(bundle)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(bundle)
                return
            values = {key: params.get(key, [""])[0] for key in (
                "site_label", "base_domain", "timezone", "dns_resolver", "backup_kind", "container_prefix")}
            try:
                plan = validate(values)
                save_plan(state_path, plan)
            except (ValueError, OSError) as exc:
                return self._reply(400, render(values, csrf, error=str(exc),
                                                dns_suggestion=detect_network_dns()))
            self.send_response(303)
            self.send_header("Location", "/discovery")
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
