#!/usr/bin/env python3
"""Offline safety-contract tests. Does not connect to LDAP, IMAP, SMTP or Paperless."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/mail_backend"


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


try:
    from jinja2 import Environment
except ImportError:  # pragma: no cover - environment without Ansible/Jinja2
    Environment = None


def truth(value: object) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


@unittest.skipIf(Environment is None, "Jinja2 not installed")
class AliasRoutingTests(unittest.TestCase):
    def render(self, filename: str, *, enabled: bool) -> str:
        env = Environment(autoescape=False)
        env.filters["bool"] = truth
        return env.from_string((ROLE / "templates" / filename).read_text()).render(
            mail_backend_aliases=[],
            mail_backend_paperless_intake_enabled=enabled,
            mail_backend_paperless_scan_domain="thebergens.net",
            mail_backend_paperless_account="paperless",
            mail_backend_primary_domain="thebergens.net",
        )

    def test_default_config_does_not_publish_any_scan_alias(self):
        text = self.render("postfix-virtual-aliases.j2", enabled=False)
        self.assertNotIn("scan-familie@", text)
        self.assertNotIn("scan-eltern@", text)

    def test_two_explicit_receiver_routes_only(self):
        text = self.render("postfix-virtual-aliases.j2", enabled=True)
        rows = [x.strip() for x in text.splitlines()
                if x.strip() and not x.startswith("#")]
        self.assertEqual(rows, [
            "scan-familie@thebergens.net paperless+familie@thebergens.net",
            "scan-eltern@thebergens.net paperless+eltern@thebergens.net",
        ])

    def test_scan_aliases_never_get_send_as_grants(self):
        text = self.render("postfix-sender-login-aliases.j2", enabled=True)
        self.assertNotIn("scan-familie@", text)
        self.assertNotIn("scan-eltern@", text)


class SafetyContractTests(unittest.TestCase):
    def test_explicit_opt_in_is_off(self):
        defaults = read("ansible/roles/mail_backend/defaults/main.yml")
        self.assertRegex(defaults, r"(?m)^mail_backend_paperless_intake_enabled: false$")

    def test_sieve_has_fixed_destinations_and_safe_fallback(self):
        script = read("ansible/roles/mail_backend/templates/paperless-intake.sieve.j2")
        routes = re.findall(r'fileinto "([^"]+)";', script)
        self.assertEqual(routes, ["Familie/Eingang", "Eltern/Eingang"])
        self.assertIn('envelope :detail :is "to" "familie"', script)
        self.assertIn('envelope :detail :is "to" "eltern"', script)
        self.assertIn("keep;", script)
        self.assertNotRegex(script, r'(?im)^\s*(discard|redirect)\s*;')
        self.assertNotIn('header :contains "Subject"', script)
        self.assertNotIn('fileinto :create', script)

    def test_existing_mail_senders_not_reconfigured(self):
        senders = read("ansible/roles/mail_backend/templates/postfix-sender-login-aliases.j2")
        self.assertNotIn("mail_backend_paperless_intake_enabled", senders)

    def test_no_shared_acl_automation_before_authorization_audit(self):
        source = read("ansible/roles/mail_backend/tasks/paperless_intake.yml")
        self.assertNotIn("acl set", source)
        self.assertNotIn("doveadm acl", source)
        self.assertNotIn("rm -", source)
        self.assertIn("paperless_mail_intake_existing_folders.stdout_lines", source)

    def test_preflight_refuses_unmanaged_personal_script(self):
        source = read("ansible/roles/mail_backend/tasks/paperless_intake_preflight.yml")
        self.assertIn("Refuse to overwrite an unmanaged Sieve script", source)
        self.assertIn("Refuse global Sieve enablement while unrelated scripts exist", source)


if __name__ == "__main__":
    unittest.main()
