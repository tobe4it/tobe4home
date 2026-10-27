# tobe4home – Prüf- und Integrationshandbuch (Stand 27.10.2026)

**Status: Entwicklungsprototyp mit real laufendem Ansible-CT 1001; die
AnsibleForms-/OpenTofu-Laufzeit ist auf dem CT noch NICHT installiert.**
Die nachfolgenden Tests sind zunächst **read-only**. Keine CTs werden
angelegt, verändert oder gelöscht.

## Entscheidung / Versionen

- **AnsibleForms 7.4.2** (Release 27.10.2026; GPL-3.0) wird Webportal,
  mehrstufiges Eingabeformular und Job-/Approval-Frontend. Offizielle
  Rocky-Linux-/systemd-Nativinstallation kann einen ggf. nicht
  unterstützten verschachtelten Podman-Setup ersetzen. Die App und die
  getrennte RTE haben je eigene Dienste; erst nach Kompatibilitäts-,
  Backup-, TLS- und Identitätsabnahme installieren.
- **OpenTofu** mit bpg/Proxmox-Provider **0.118.0** (Version im erzeugten
  HCL fest gepinnt). Der Provider zielt auf Proxmox VE 9.x ab; 8.x
  mit Einschränkungen. **PVE-Version von venombox ist noch zu prüfen.**
- **Ansible** übernimmt die Konfiguration IN den neuen Gästen, während
  OpenTofu den deklarativen Gast-/Storage-/Netz-Lifecycle übernimmt.
  Keine konkurrierenden `pct create`- und OpenTofu-Installationen.
- **CT 1001**: Der Nutzer hat die funktionierende Ansible-Installation
  mit Core 2.16.16, Python 3.12 und `ping: pong` sowie aktivem SSH
  bestätigt. Dieses Systempaket nicht löschen oder überschreiben.
  Die AnsibleForms-RTE wird separat und in einer unterstützten Version
  aufgebaut; Core 2.16 ist upstream bereits EOL.
- **CT 1000**: Alte Setup-WebApp und gespeicherte Konfiguration bleiben
  unangetastet, bis der spätere Umzug bestätigt ist.

## Bereits implementierte Artefakte

| Pfad | Zweck | Schreiben auf Proxmox? |
| --- | --- | --- |
| `bootstrap/import_stage0_site.py` | read-only Übernahme whitelisted Standortfelder aus CT1000 für lokale Testpläne | Nein |
| `bootstrap/pve_snapshot.py` | ausschließlich GET-Aufrufe über lokales `pvesh` für VMIDs, Bridge, Storage, Vorlage, freie Ressourcen | Nein |
| `bootstrap/infra_planner.py` | deterministischer Bedarfs- und VMID-Planer, Kapazitäts-/Sicherheitsprüfungen und SHA-256 des Plans | Nein |
| `bootstrap/infra_planner.py --tf` | OpenTofu-HCL für neue, zunächst gestoppte und gegen Löschen geschützte LXCs | Nein |
| `bootstrap/infra_planner.py --html` | eigenständige, lokale Topologiegrafik aus demselben Plan | Nein |
| `ansibleforms/forms/tobe4home-infra-preview.yml` | zweistufiger deutschsprachiger AnsibleForms-7-Wizard | Noch nicht deployed |
| `ansibleforms/playbooks/tb4h-preview.yml` | ausschließlich lokaler, nicht privilegierter Ansible-Preview-Job mit synthetischem Inventar | Nein |
| `examples/infra-preview/*.json` | vollständig synthetische, öffentliche Beispieldaten | Nein |
| `tests/test_infra_planner.py` / `test_pve_snapshot.py` / `test_ansibleforms_preview.py` | Regressionen inkl. Negativein-/Ausgaben, Secret- und Berechtigungsgrenzen | Nein |

**Wichtig:** Die Wizard- und Beispiel-Dateien sind ein **Integrationstest**,
keine produktive AnsibleForms-Form. Sie verwenden absichtlich
`examples/infra-preview/inventory.example.json`; es gibt darin keinen
Proxmox-API-Token oder Host-Schreibrechte. Die RTE-Pfade und die Form-
Validierung müssen nach einer realen AnsibleForms-Installation geprüft werden.
Der generierte OpenTofu-Code ist eine **Vorschau, keine verbindliche
Transaktionsfreigabe**, kein echter providerseitiger `tofu plan`, und er
enthält bewusst keine Zugangsdaten oder automatische Ausführung.

## 1. Ohne Proxmox-Zugriff: Plan und grafisches Modell ansehen

In einem Checkout des aktuellen Feature-Branches mit Python 3.10+
(z. B. direkt auf venombox):

```bash
cd /root/tobe4home-bootstrap
git pull --ff-only
python3 -m unittest discover -s tests -p 'test_infra_planner.py'
python3 bootstrap/infra_planner.py \
  --site examples/infra-preview/site.example.json \
  --choices examples/infra-preview/choices.example.json \
  --inventory examples/infra-preview/inventory.example.json

python3 bootstrap/infra_planner.py \
  --site examples/infra-preview/site.example.json \
  --choices examples/infra-preview/choices.example.json \
  --inventory examples/infra-preview/inventory.example.json \
  --html > /tmp/tb4h-plan-demo.html
```

Die HTML-Datei ist offline anzeigbar. Für den Beispieldatensatz sollten
**drei** neue Gäste mit VMIDs **1002, 1003, 1005** geplant werden;
**1004** ist absichtlich belegt und ein bereits verifizierter
Modell-Endpunkt wird wiederverwendet.

Auch OpenTofu-Vorschau ohne API-Zugriff:

```bash
python3 bootstrap/infra_planner.py \
  --site examples/infra-preview/site.example.json \
  --choices examples/infra-preview/choices.example.json \
  --inventory examples/infra-preview/inventory.example.json \
  --tf > /tmp/tb4h-preview.tf
```

`--tf` führt **weder `tofu init` noch `plan` oder `apply`** aus.

## 2. Read-only-Inventar auf venombox

Auf einem unterstützten Proxmox-Host:

```bash
umask 077
sudo python3 /root/tobe4home-bootstrap/bootstrap/pve_snapshot.py \
  --node venombox --template-storage local \
  > ~/tobe4home-pve-inventory.local.json
```

Der Export enthält ausschließlich deklarierte Metadaten und keine
Credentials. Er ermittelt den Clusterbestand einschließlich der existierenden
CTs 1000/1001, aktiven Bridges, Storage-Typen, Templates und die freie
Hostkapazität. **Keine öffentlichen Commits echter Standortdaten.**

Die relevanten bestehenden Stage-0-Vorgaben lassen sich ohne
Schreibzugriffe und ohne Wiederholung der Benutzereingaben übernehmen:

```bash
sudo python3 /root/tobe4home-bootstrap/bootstrap/import_stage0_site.py \
  --node venombox --bridge vmbr3 --storage local-zfs \
  --template local:vztmpl/rockylinux-10-default_20251001_amd64.tar.xz \
  > ~/tobe4home-planner-site.local.json
```

Der Import liest nur Präfix und DNS aus CT 1000, ergänzt die explizit
geprüften Host-/Storage-/Bridge-Parameter und gibt ausschließlich
diese Whitelist-Felder aus. **Kein Site-Secret, kein Passwort und keine
LXC-Änderung.** Die tatsächliche DNS-Erreichbarkeit ist vor der späteren
Provisionierung separat zu überprüfen. Neue Bestandsdaten werden nicht
blind als freigegebene Schreibaufträge verwendet.

Das echte Inventar plus die lokal gespeicherten Site-Daten können
anschließend unter kontrollierter operatorseitiger Auswahl in die
`--inventory`- und `--site`-Optionen der Planner-CLI eingesetzt
werden. Erforderliche `existing_services`-Einträge müssen als
**tatsächlich verifiziert** gekennzeichnet werden; bei unbekannter
Endpoint-Konfiguration verweigert der Planer den Existing-Modus.
Die privaten Dateien sind lokal mit Mode 0600 aufzubewahren und dürfen
nicht ins öffentliche Git-Repository.

## 3. Realtest-Gates vor Installation von AnsibleForms

Zuerst lediglich erheben und prüfen:

```bash
sudo pct config 1001
sudo pct exec 1001 -- cat /etc/os-release
sudo pct exec 1001 -- systemctl is-system-running
sudo pct exec 1001 -- df -h /
sudo pct exec 1001 -- free -h
sudo pct exec 1001 -- ansible --version
sudo pveversion
```

Für die native Rocky-Installation verlangt der Upstream-Installer
systemd, MariaDB, Node.js, Python, Ansible-RTE, Git und Zugriff auf
die Paketquellen. Offizielle Dokumentation:
https://ansibleforms.com/en/installation/native.html

AnsibleForms/Installer nicht als ungeprüften `curl | sh`-Befehl
unter Root ausführen. **Version und Quelle pinnen**, den upstream
Release-Bundle mit veröffentlichter SHA-256-Seiten-Datei prüfen,
Installationscode auditieren, benötigte Ressourcen/Zugriffsgrenzen und
Portbelegung prüfen, einen Wiederherstellungspunkt für CT 1001
vorbereiten. Erst dann mit ausdrücklicher Betreiberfreigabe eine
Installationsautomation aktivieren. Ein getrennter AnsibleForms-RTE darf
keinen generellen Root-SSH-/Proxmox-API-Zugang erhalten.

Die UI-/Datenbank-Installation wird erst als erledigt markiert, wenn
`systemctl`/HTTP-Healthchecks, lokaler Login, ein echter Wizard-Launch,
Playbookpfade und deren Ausführung sowie Backup und Restore bestanden
wurden.

## 4. Vor dem ersten OpenTofu-Apply

Kein `tofu apply` auf einem ungesicherten neuen State. Benötigte Gates:

1. Exakte PVE-Version, Node, Storage, VMID und Templates bestätigen.
2. Dedizierte **minimal berechtigte** API-Identität getrennt von
   AnsibleForms-Frontend/Agenten; TLS-Validierung und Secrets geschützt.
3. Unveränderliches Plan-Manifest mit Inventarrevision und Fingerprint;
   Race-/Drift-Prüfung direkt vor Apply.
4. Privates, gesperrtes und gesichertes OpenTofu-State-Backend;
   Importstrategien für bestehende Gäste **vor** Ressourcenzuweisung.
5. `tofu init` mit Provider-Lockfile, `tofu validate`, `tofu plan -out`
   und `tofu show -json` mit Prüfung erlaubter Resource-Actions.
6. Konkrete Jobfreigabe **für diesen** Plan; `apply` darf ausschließlich
   auf den zuvor gespeicherten geprüften Plan laufen, nie blind auf
   fremder Infrastruktur. Nach Anlage separate Ansible-Healthchecks.
7. Explizite Fehlerbehandlung, Zustands-Resume und Restore-Test.
   Stoppen, falls die Anbieter-API den Plan nicht vollständig unterstützt.

Die aktuell erzeugten Dateien **führen keinen dieser Apply-Schritte
automatisch aus**.

## Offene Umsetzung nach dieser Lieferung

- [ ] Echte AnsibleForms-7-Runtime (native/Podman-Entscheidung) in CT 1001
      installiert und in der realen Weboberfläche getestet.
- [ ] Standort- und Ressourcen-Auswahl im Wizard statt des Demo-Inventars,
      sichere Migration der Stage-0-Angaben in CT 1001.
- [ ] Automatisierte, rollenbegrenzte Proxmox-Discovery aus CT 1001
      (zunächst nur lesend); lokaler `pvesh`-Exporter ist der Zwischenschritt.
- [ ] OpenTofu-State-/Approval-/Apply-Gateway mit realem Plan-/Drift-/API-Test.
- [ ] Neue Gäste nach Freigabe mit Ansible konfigurieren und healthchecken.
- [ ] Git, Agent, CI, Modellanbieter und Prompt→PR→Test→Deployment anbinden.
- [ ] Wiederherstellungs- und Versionsupgradetests bestehen, erst danach
      CT 1000 optional stilllegen.

## Wartbarkeit

Die Host- und Guest-Änderungen an der bestehenden `venombox`-Installation
werden in diesem Entwicklungsstand **nicht** automatisch durchgeführt.
Dadurch kann der Nutzer den GitHub-Branch und die synthetischen Ergebnisse
vor realem Deployment vollständig prüfen.

Architektur: [ADR 001](ADR-001-SINGLE-CONTROLLER.md),
[ADR 002](ADR-002-ANSIBLEFORMS-UI.md),
[Orchestrator](INSTALLATION-ORCHESTRATOR.md).
