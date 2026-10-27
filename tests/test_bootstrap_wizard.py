"""Non-privileged tests for the stage-0 installer wizard."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap" / "wizard.py"
spec = importlib.util.spec_from_file_location("wizard", SCRIPT)
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)

GOOD = {
    "site_label": "Demo Home",
    "base_domain": "home.example.org",
    "timezone": "Europe/Berlin",
    "dns_resolver": "192.0.2.53",
    "backup_kind": "nas",
    "container_prefix": "tobe4home",
}

class WizardTests(unittest.TestCase):
    def test_plan_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.local.json"
            wizard.save_plan(path, wizard.validate(GOOD))
            self.assertEqual(wizard.load_plan(path), GOOD)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn('"deployment_enabled": false', path.read_text())

    def test_invalid_dns_and_domain(self):
        for k, value in (("dns_resolver", "not-an-ip"),
                         ("base_domain", "bad domain"),
                         ("backup_kind", "unverified")):
            with self.subTest(key=k):
                payload = dict(GOOD, **{k: value})
                with self.assertRaises(ValueError):
                    wizard.validate(payload)

    def test_custom_container_prefix(self):
        values = dict(GOOD, container_prefix="familienhaus-")
        self.assertEqual(wizard.validate(values)["container_prefix"], "familienhaus")
        self.assertEqual(wizard.normalized_prefix("lab-"), "lab")
        self.assertEqual(wizard.normalized_prefix("x"), "x")
        for invalid in ("", "-bad", "Bad", "my_prefix", "a..b", "z" * 58):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    wizard.normalized_prefix(invalid)

    def test_prefix_is_in_local_wizard(self):
        page = wizard.render(GOOD, "token")
        self.assertIn('name="container_prefix"', page)
        self.assertIn('value="tobe4home"', page)
        self.assertIn("dieser Setup-Container wird nicht umbenannt", page)

    def test_output_escapes_rendered_input(self):
        payload = dict(GOOD, site_label='<script>alert(1)</script>')
        html = wizard.render(payload, "test-token")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_unauthorized_file_is_not_read_as_valid_site(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.local.json"
            path.write_text('{"site":{"site_label":"x"}}')
            self.assertEqual(wizard.load_plan(path), {})

    def test_navigation_has_real_next_step_and_no_double_phase_numbering(self):
        draft = dict(GOOD)
        page = wizard.render(draft, "csrf")
        self.assertIn('action="/save"', page)
        self.assertIn('Weiter zur Bestandsaufnahme', page)
        self.assertIn('href="/discovery"', page)
        self.assertIn('href="/plan"', page)
        self.assertNotIn('1. 00', page)
        self.assertNotIn('SSH-only administration', page)

    def test_plan_and_guest_discovery_escape_all_data(self):
        facts = {"hostname": '<img src=x onerror=alert(1)>',
                 "os": "Rocky Linux 10", "guest_ipv4": "192.0.2.100",
                 "dns": "192.0.2.53", "dns_origin": "DHCP"}
        result = wizard.render_discovery(dict(GOOD), facts)
        self.assertIn("Bestandsaufnahme", result)
        self.assertIn("192.0.2.100", result)
        self.assertIn("&lt;img src=x", result)
        self.assertNotIn("<img src=", result)
        plan = wizard.render_plan(dict(GOOD))
        self.assertIn("Gespeicherte Konfiguration", plan)
        self.assertIn("Implementierung ausstehend", plan)
        self.assertNotIn('action="/apply"', plan)
        self.assertIn("keinen eingeschränkt berechtigten", plan)

    def test_full_setup_navigation_requires_saved_plan(self):
        import base64
        import re
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "site.local.json"
            code = "test-key-that-is-at-least-32-chars"
            handler = wizard.make_handler(state, code)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                token = base64.b64encode(("setup:" + code).encode()).decode()
                auth = {"Authorization": "Basic " + token}
                def fetch(path, payload=None):
                    if payload is None:
                        request = Request(base + path, headers=auth)
                    else:
                        request = Request(base + path,
                                          data=urlencode(payload).encode(),
                                          headers=auth)
                    with urlopen(request, timeout=3) as response:
                        return response.geturl(), response.read().decode()
                address, starting = fetch("/discovery")
                self.assertEqual(address, base + "/")
                csrf = re.search(r'name="csrf" value="([^"]+)"', starting)
                self.assertIsNotNone(csrf)
                values = dict(GOOD, csrf=csrf.group(1))
                address, discovered = fetch("/save", values)
                self.assertEqual(address, base + "/discovery")
                self.assertIn("Bestandsaufnahme", discovered)
                self.assertTrue(state.exists())
                self.assertIn("Weiter zum Installationsplan", discovered)
                address, planned = fetch("/plan")
                self.assertEqual(address, base + "/plan")
                self.assertIn("Installationsreihenfolge", planned)
                self.assertIn("Keine weitere Installation freigegeben", planned)
                self.assertNotIn("/apply", planned)
                request = Request(base + "/apply", data=b"", headers=auth)
                with self.assertRaises(HTTPError) as attempted:
                    urlopen(request, timeout=3)
                self.assertEqual(attempted.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)

    def test_all_pages_require_setup_code(self):
        import base64
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        with tempfile.TemporaryDirectory() as temp:
            state_file = Path(temp) / "state.json"
            code = "test-secret-with-32-plus-characters"
            handler = wizard.make_handler(state_file, code)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with self.assertRaises(HTTPError) as unauth:
                    urlopen(base + "/", timeout=3)
                self.assertEqual(unauth.exception.code, 401)
                self.assertIn("Basic", unauth.exception.headers["WWW-Authenticate"])
                token = base64.b64encode(("setup:" + code).encode()).decode()
                req = Request(base + "/health",
                              headers={"Authorization": "Basic " + token})
                with urlopen(req, timeout=3) as response:
                    self.assertEqual(response.read(), b"ok")
                req = Request(base + "/",
                              headers={"Authorization": "Basic " + token})
                with urlopen(req, timeout=3) as response:
                    self.assertIn(b"tobe4home Setup", response.read())
                self.assertFalse(state_file.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_short_setup_code_rejected(self):
        with self.assertRaises(ValueError):
            wizard.make_handler(Path("/tmp/example.json"), "too-short")

    def test_tls_required_by_executable_entry_point(self):
        script = SCRIPT.read_text()
        self.assertIn("ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)", script)
        self.assertIn("tls.load_cert_chain", script)
        self.assertIn('default="0.0.0.0"', script)
        self.assertIn("def _require_auth(self)", script)

    def test_dns_sources_are_parsed_without_guessing(self):
        self.assertEqual(wizard.parse_dhcp_dns(
            "GENERAL.DEVICE: eth0\n"
            "DHCP4.OPTION[1]: domain_name_servers = 10.50.0.53 10.50.0.54\n"
            "IP4.DNS[1]: 203.0.113.1\n"),
            ["10.50.0.53", "10.50.0.54"])
        self.assertEqual(wizard.parse_dhcp_dns("IP4.DNS[1]: 203.0.113.1"),
                         [])
        self.assertEqual(wizard.parse_resolv_conf(
            "# --- BEGIN PVE ---\nnameserver 127.0.0.53\n"
            "nameserver 10.50.0.53\nnameserver 10.50.0.53\n"),
            ["10.50.0.53"])
        self.assertEqual(wizard.parse_resolv_conf("nameserver 127.0.0.1"), [])

    def test_dhcp_suggestion_is_labeled_and_different_effective_dns_warns(self):
        import subprocess
        from unittest.mock import patch
        command = subprocess.CompletedProcess(
            [], 0, "DHCP4.OPTION[1]: domain_name_servers = 10.50.0.53\n", "")
        with patch.object(wizard.subprocess, "run", return_value=command):
            with patch.object(wizard.Path, "read_text",
                              return_value="# --- BEGIN PVE ---\nnameserver 10.50.0.1\n"):
                info = wizard.detect_network_dns()
        self.assertEqual(info["value"], "10.50.0.53")
        self.assertIn("DHCP", info["source"])
        self.assertIn("Achtung", info["warning"])

    def test_effective_resolver_fallback_not_mislabeled_dhcp(self):
        import subprocess
        from unittest.mock import patch
        command = subprocess.CompletedProcess([], 127, "", "not installed")
        with patch.object(wizard.subprocess, "run", return_value=command):
            with patch.object(wizard.Path, "read_text",
                              return_value="# --- BEGIN PVE ---\nnameserver 10.50.0.53\n"):
                info = wizard.detect_network_dns()
        self.assertEqual(info["value"], "10.50.0.53")
        self.assertIn("nicht bestätigt", info["source"])

    def test_dns_prefill_respects_saved_value_and_escapes_source(self):
        discovered = {"value": "10.50.0.53",
                      "source": "DHCP-Option 6 (eth0)",
                      "warning": ""}
        page = wizard.render({}, "token", dns_suggestion=discovered)
        self.assertIn('name="dns_resolver"', page)
        self.assertIn('value="10.50.0.53"', page)
        self.assertIn("DHCP-Option 6 (eth0)", page)
        saved = wizard.render(dict(GOOD), "token", dns_suggestion=discovered)
        self.assertIn('value="192.0.2.53"', saved)
        self.assertNotIn('value="10.50.0.53"', saved)
        suspicious = dict(discovered, source="<script>alert(1)</script>")
        escaped = wizard.render({}, "token", dns_suggestion=suspicious)
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;script&gt;", escaped)

    def test_all_prerequisites_are_present(self):
        names = [name for _, name, _ in wizard.PHASES]
        self.assertEqual(len(names), 7)
        self.assertIn("Recovery and backups", names)

if __name__ == "__main__":
    unittest.main()
