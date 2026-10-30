#!/usr/bin/env python3
"""tobe4home Chat MVP: loopback-only, non-executing LLM dialog.

NO Proxmox access, credentials, shell, Ansible invocation or deployment.
Access exclusively via an authenticated SSH tunnel to CT1001.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import sys
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPHandler, HTTPSHandler, ProxyHandler, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("TB4H_CHAT_CONFIG", "/etc/tobe4home/chat.json"))
HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST = 24_000
MAX_RESPONSE = 65_536
ALLOWED_ROLES = frozenset({"user", "assistant"})
MODE = "READ_ONLY_PREVIEW"
SYSTEM = (
    "Du bist der planende Assistent für tobe4home. Antworte auf Deutsch, "
    "knapp und präzise. Die Infrastruktur wird NICHT automatisch verändert. "
    "Der Benutzer wünscht Dienste wie Paperless-ngx, DNS-Filter, filternden "
    "Proxy und Mailserver. Erkläre nur einen unverbindlichen Plan: Ziel, "
    "Voraussetzungen, mögliche Ansible-Rollen, benötigte LXC/Ressourcen, "
    "DNS/Ports, TLS, Berechtigungen, Backup/Restore, Risiken, Gesundheitstests. "
    "Frage nur nach nicht verlässlich erkennbaren Angaben. Bestehende Proxmox-"
    "Gäste niemals automatisch übernehmen oder ändern. Liefere weder echte "
    "Deployment-Zusagen noch Shell-Anweisungen zum Umgehen von Freigaben. "
    "Weder ein Prompt noch eine Antwort bewirkt eine Ausführung. "
    "Niemals Geheimnisse oder Zugangsdaten erfragen."
)


class ChatError(Exception):
    pass


def config_from(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"api_url", "model"}:
        raise ChatError("Konfiguration braucht nur api_url und model")
    url, model = raw["api_url"], raw["model"]
    if not isinstance(url, str) or not isinstance(model, str):
        raise ChatError("Ungültige LLM-Konfiguration")
    if not url and not model:
        return {"api_url": "", "model": ""}
    if not 1 <= len(model) <= 128 or not re.fullmatch(r"[a-zA-Z0-9._:/-]+", model):
        raise ChatError("Ungültiger Modellname")
    parsed = urlsplit(url)
    local = parsed.hostname in {"127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and local)):
        raise ChatError("LLM-API erfordert TLS; HTTP nur für localhost")
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path != "/v1/chat/completions" or not parsed.hostname or
            not parsed.port and parsed.netloc.endswith(":")):
        raise ChatError("Ungültige LLM-API-Adresse")
    if len(url) > 500:
        raise ChatError("LLM-API-Adresse zu lang")
    return {"api_url": url, "model": model}


def load_config(path: Path = CONFIG_PATH) -> dict:
    info = path.lstat()
    if not info.st_mode & 0o170000 == 0o100000 or info.st_nlink != 1 or info.st_size > 2048:
        raise ChatError("Konfigurationsdatei ist nicht regulär")
    if info.st_mode & 0o022:
        raise ChatError("Konfiguration darf nicht gruppen-/welt-schreibbar sein")
    if info.st_uid != 0:
        raise ChatError("Konfiguration muss root gehören")
    try:
        return config_from(json.loads(path.read_text(encoding="utf-8")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ChatError("Ungültige Konfigurationsdatei") from exc


def validated_messages(payload: object) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or set(payload) != {"messages"}:
        raise ChatError("Ungültige Chatnachricht")
    messages = payload["messages"]
    if not isinstance(messages, list) or not 1 <= len(messages) <= 10:
        raise ChatError("1 bis 10 Chatnachrichten sind zulässig")
    out = []
    for msg in messages:
        if not isinstance(msg, dict) or set(msg) != {"role", "content"}:
            raise ChatError("Ungültige Nachrichtenstruktur")
        if msg["role"] not in ALLOWED_ROLES or not isinstance(msg["content"], str):
            raise ChatError("Unzulässige Nachricht")
        content = msg["content"].strip()
        if not 1 <= len(content) <= 1600 or "\x00" in content:
            raise ChatError("Nachricht zu lang oder leer")
        out.append({"role": msg["role"], "content": content})
    if out[-1]["role"] != "user":
        raise ChatError("Letzte Nachricht muss vom Benutzer stammen")
    return out


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ChatError("LLM-API darf nicht weiterleiten")


def call_model(config: dict, messages: list[dict], credential_dir: str = "") -> str:
    if not config["api_url"]:
        raise ChatError("LLM-Endpunkt noch nicht konfiguriert; nur lokale Vorschau verfügbar")
    request_data = json.dumps({
        "model": config["model"],
        "messages": [{"role": "system", "content": SYSTEM}, *messages],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 1400,
        "tools": [],
    }, ensure_ascii=False).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if credential_dir:
        token_path = Path(credential_dir) / "llm_api_key"
        if token_path.is_file():
            key = token_path.read_text(encoding="utf-8").strip()
            if key:
                if len(key) > 2048 or any(x in key for x in ("\n", "\r")):
                    raise ChatError("Ungültiges LLM-Zugangstoken")
                headers["Authorization"] = "Bearer " + key
    req = Request(config["api_url"], data=request_data, headers=headers, method="POST")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    try:
        with opener.open(req, timeout=40) as response:
            if response.status != 200:
                raise ChatError("LLM-Endpunkt meldet Fehler")
            if "json" not in response.headers.get("Content-Type", ""):
                raise ChatError("LLM-Endpunkt lieferte kein JSON")
            raw = response.read(MAX_RESPONSE + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ChatError("LLM-Endpunkt nicht verfügbar; keine Änderungen durchgeführt") from exc
    if len(raw) > MAX_RESPONSE:
        raise ChatError("LLM-Antwort überschreitet die Grenze")
    try:
        data = json.loads(raw)
        answer = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ChatError("LLM-Antwortformat nicht unterstützt") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise ChatError("LLM lieferte keine Textantwort")
    return answer[:8000]


def make_handler(config: dict):
    csrf = secrets.token_urlsafe(32)
    static = {
        "/": ("text/html; charset=utf-8", ROOT / "index.html"),
        "/app.js": ("text/javascript; charset=utf-8", ROOT / "app.js"),
        "/app.css": ("text/css; charset=utf-8", ROOT / "app.css"),
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "tobe4home-chat-mvp"
        sys_version = ""

        def log_message(self, fmt, *args):
            # Never log prompts, responses, URL credentials or browser headers.
            pass

        def headers_safe(self):
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}

        def send_data(self, status: int, data: bytes, content_type: str):
            self.send_response(status)
            for key, value in {
                "Content-Type": content_type,
                "Content-Length": str(len(data)),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            }.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def respond(self, status: int, result: dict):
            self.send_data(status, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            if not self.headers_safe():
                self.respond(403, {"error": "Ungültiger Host"})
                return
            if self.path == "/api/status":
                self.respond(200, {"mode": MODE, "configured": bool(config["api_url"]), "model": config["model"], "csrf": csrf})
            elif self.path in static:
                mime, path = static[self.path]
                self.send_data(200, path.read_bytes(), mime)
            else:
                self.respond(404, {"error": "Nicht gefunden"})

        def do_POST(self):
            if not self.headers_safe():
                self.respond(403, {"error": "Ungültiger Host"})
                return
            if self.path != "/api/chat":
                self.respond(404, {"error": "Nicht gefunden"})
                return
            origin = self.headers.get("Origin", "")
            if origin not in {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"} or not hmac.compare_digest(
                    self.headers.get("X-TB4H-CSRF", ""), csrf):
                self.respond(403, {"error": "Chat-Zugriff nicht autorisiert"})
                return
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or not 1 <= int(length) <= MAX_REQUEST:
                self.respond(413, {"error": "Nachricht zu groß"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self.respond(415, {"error": "Nur JSON zulässig"})
                return
            try:
                messages = validated_messages(json.loads(self.rfile.read(int(length))))
                answer = call_model(config, messages, os.environ.get("CREDENTIALS_DIRECTORY", ""))
            except (ValueError, ChatError) as exc:
                self.respond(422, {"error": str(exc)})
                return
            self.respond(200, {"reply": answer, "mode": MODE})

    return Handler


def main() -> int:
    if os.geteuid() == 0:
        print("Chat darf nicht als root laufen", file=sys.stderr)
        return 2
    try:
        config = load_config()
    except (ChatError, OSError) as exc:
        print("TOBE4HOME_CHAT_CONFIGURATION_ERROR: " + str(exc), file=sys.stderr)
        return 2
    print(f"TOBE4HOME_CHAT_BIND={HOST}:{PORT} MODE={MODE} MODEL_CONFIGURED={bool(config['api_url'])}", flush=True)
    with ThreadingHTTPServer((HOST, PORT), make_handler(config)) as server:
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
