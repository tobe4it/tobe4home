"""Review-only Stage-1 CT installer policy checks."""
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "bootstrap" / "deploy-ansible-controller.sh"


class Stage1InstallerTests(unittest.TestCase):
    def test_shell_syntax(self):
        run = subprocess.run(["bash", "-n", str(SCRIPT)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_create_is_gated_and_not_delete_capable(self):
        script = SCRIPT.read_text()
        self.assertIn("VMID=1001", script)
        self.assertIn("APPLY=0", script)
        self.assertIn('if (( ! APPLY )); then', script)
        self.assertIn('read -r -p "Type DEPLOY 1001', script)
        self.assertIn('[[ "$CONFIRM" == "DEPLOY 1001" ]]', script)
        self.assertIn('pct create "$VMID"', script)
        self.assertIn('--unprivileged 1 --onboot 0', script)
        self.assertIn('umask 022', script)
        self.assertIn('pvesh get /cluster/resources', script)
        self.assertIn('lxc-usernsexec', script)
        self.assertIn('pvesm status --content rootdir', script)
        self.assertIn('pct exec "$VMID" -- ansible --version', script)
        self.assertNotIn("pct destroy", script)
        self.assertNotIn("rm -rf", script)
        self.assertNotIn("--privileged 1", script)

    def test_wizard_plan_links_to_first_real_controller_install(self):
        import importlib.util
        source = SCRIPT.parent / "wizard.py"
        spec = importlib.util.spec_from_file_location("stage1_wizard", source)
        wizard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wizard)
        values = {
            "site_label": "Home Lab", "container_prefix": "tb4h",
            "base_domain": "lab.example.org", "timezone": "Europe/Berlin",
            "dns_resolver": "192.0.2.53", "backup_kind": "nas"}
        plan = wizard.render_plan(values)
        self.assertIn('href="/infrastructure"', plan)
        handoff = wizard.render_infrastructure(values)
        self.assertIn('deploy-ansible-controller.sh', handoff)
        self.assertIn("DEPLOY 1001", handoff)
        self.assertIn("--apply", handoff)
        self.assertIn("delegierte Proxmox-API-Berechtigung", handoff)

    def test_resume_syntax_and_no_new_ct(self):
        resume = SCRIPT.parent / "resume-ansible-controller.sh"
        result = subprocess.run(["bash", "-n", str(resume)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        src = resume.read_text()
        self.assertIn('VMID=1001', src)
        self.assertIn('APPLY=0', src)
        self.assertIn('pct config "$VMID"', src)
        self.assertIn("hostname: tb4h-ansible", src)
        self.assertIn('unprivileged: 1', src)
        self.assertIn('pct exec 1000 -- python3 -c', src)
        self.assertIn('"/var/lib/tobe4home/site.local.json"', src)
        self.assertIn('pct set "$VMID" --nameserver "$DNS"', src)
        self.assertIn('read -r -p "Type RESUME 1001', src)
        self.assertIn('[[ "$CONFIRM" == "RESUME 1001" ]]', src)
        self.assertIn('timeout 15 pct exec "$VMID" -- getent ahostsv4', src)
        self.assertIn('pct exec "$VMID" -- ansible localhost', src)
        self.assertNotIn('pct create ', src)
        self.assertNotIn('pct destroy ', src)
        self.assertNotIn('rm -rf ', src)
        self.assertLess(src.index('if (( ! APPLY )); then'), src.index('pct set "$VMID"'))

    def test_new_install_inherits_explicit_saved_site_dns(self):
        src = SCRIPT.read_text()
        self.assertIn('DNS_SERVER=""', src)
        self.assertIn('--nameserver=*) DNS_SERVER=', src)
        self.assertIn('/var/lib/tobe4home/site.local.json', src)
        self.assertIn('    --nameserver "$DNS_SERVER"', src)
        self.assertIn('getent ahostsv4 mirrors.rockylinux.org', src)
        self.assertLess(src.index('    --nameserver "$DNS_SERVER"'),
                        src.index('pct exec "$VMID" -- dnf'))

    def test_no_implicit_network_or_storage_selection(self):
        script = SCRIPT.read_text()
        self.assertIn('BRIDGE=""', script)
        self.assertIn('STORAGE=""', script)
        self.assertIn("Missing/invalid --bridge", script)
        self.assertIn("Missing/invalid --storage", script)
        self.assertIn('[[ -d "/sys/class/net/$BRIDGE/bridge" ]]', script)
        self.assertIn('TEMPLATE="rockylinux-10-default_20251001_amd64.tar.xz"', script)


if __name__ == "__main__":
    unittest.main()
