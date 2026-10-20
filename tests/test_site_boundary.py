"""Ensure deployment topology stays in untracked site configuration."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VARS = ROOT / "ansible/group_vars/all"

SERVICES = {
    "bergen-ai.yml": {
        "lxc_vmid": "site_ai_backend_vmid",
        "lxc_hostname": "site_ai_backend_hostname",
        "lxc_storage": "site_lxc_storage",
        "lxc_bridge": "site_ai_bridge",
    },
    "bergen-mqtt.yml": {
        "lxc_vmid": "site_mqtt_vmid",
        "lxc_hostname": "site_mqtt_hostname",
        "lxc_storage": "site_lxc_storage",
        "lxc_bridge": "site_mqtt_bridge",
    },
    "bergen-pihole.yml": {
        "lxc_vmid": "site_pihole_vmid",
        "lxc_hostname": "site_pihole_hostname",
        "lxc_storage": "site_lxc_storage",
        "lxc_bridge": "site_pihole_bridge",
    },
    "bergen-syslog.yml": {
        "lxc_vmid": "site_syslog_vmid",
        "lxc_hostname": "site_syslog_hostname",
        "lxc_storage": "site_lxc_storage",
        "lxc_bridge": "site_syslog_bridge",
    },
    "bp-controller.yml": {
        "lxc_vmid": "site_controller_vmid",
        "lxc_hostname": "site_controller_hostname",
        "lxc_storage": "site_lxc_storage",
        "lxc_bridge": "site_controller_bridge",
    },
}


def test_site_bound_container_settings_are_not_literal():
    for filename, expected in SERVICES.items():
        values = yaml.safe_load((VARS / filename).read_text(encoding="utf-8"))
        for key, variable in expected.items():
            assert values[key] == "{{ " + variable + " | mandatory }}", (filename, key)


def test_public_example_documents_every_required_setting():
    sample = yaml.safe_load((VARS / "site.local.yml.example").read_text(encoding="utf-8"))
    required = {variable for settings in SERVICES.values() for variable in settings.values()}
    assert all(variable in sample for variable in required)
    assert sample["site_lxc_storage"] == "CHANGE_ME"


def test_local_override_is_ignored_by_git_patterns():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "ansible/group_vars/all/site.local.yml" in ignore
    assert "ansible/inventory.local.yml" in ignore
