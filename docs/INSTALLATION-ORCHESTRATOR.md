# tobe4home – Promptgesteuerter Neuinstallations-Orchestrator

Status: **Zielarchitektur / Implementierungsvertrag, nicht bereits installiert.**
Dieses Dokument beschreibt die Neuinstallation der Plattform. Ein Backup-/Recovery-
Export ist ein optionales Betriebswerkzeug und **kein Installationsschritt, der den
Hauptweg ersetzt**.

## 1. Ausgangspunkt und Ziel

Ausgangspunkt: ein vorhandener Proxmox-Host mit funktionsfähigem unprivilegiertem
Rocky-Linux-10-Setup-LXC, dessen WebApp über das vom Administrator gewählte interne
Netz erreichbar ist.

Die WebApp soll:
1. Standort- und Infrastrukturparameter erfassen und valide lokal speichern.
2. Über **read-only** angebundene Proxmox-/Netzwerk-Discovery nur tatsächlich
   belegbare Eigenschaften erkennen; manuelle Angaben und Herkunft unterscheiden.
3. Einen reproduzierbaren **Minimalplan** für die erforderliche Installations-
   und Entwicklungsumgebung mit Storage-, Netz-, OS-, Ressourcen- und
   Berechtigungsbedarf berechnen.
4. In einer klar abgegrenzten, einmalig autorisierten Bootstrap-Phase genau
   diese **notwendigen Infrastruktur-Gäste** erstellen, starten und verifizieren.
5. Die Nutzerin/den Nutzer über vorgegebene, versionierte, anpassbare Prompts
   zur weiteren Ausgestaltung der Plattform führen.
6. Aus Prompt + geprüften Site-Parametern via isoliertem Coding-Agent einen
   **Git-Branch/PR mit konkreten Ansible-Artefakten** erstellen; nie direkt
   ein vom Modell erzeugtes Shell-Skript als Hypervisor-root ausführen.
7. Nach automatischer statischer Prüfung, Plan/Diff-Anzeige, Freigabe und
   wiederholbaren Bereitstellungsgates die Ansible-Artefakte über einen
   kontrollierten Job-Runner deployen.
8. Status, Task-Ergebnis, Fehler, Wiederaufnahme und Export-/Backup-/Restore-
   Prüfungen über die WebApp beobachtbar machen.

**Prinzip:** Die UI ist Bedien- und Freigabeschicht. Generierter Code ist
unvertrauenswürdig bis geprüft und freigegeben. Die Installation ist GitOps-
gestützt, idempotent und rückverfolgbar, nicht Chat → root-Shell.

## 2. Minimale logische Rollen

| Rolle | Vorschlag für neuen Gast | Zwingend für welchen Modus? | Aufgabe |
| --- | --- | --- | --- |
| Setup/Orchestrator | bereits vorhanden, z. B. CT 1000 | Immer | Formular, Discovery, Plan und Freigaben, **keine Proxmox-root-Shell** |
| Ansible-/Deployment-Controller | z. B. CT 1001 | Immer, sofern keine gleichwertige dedizierte Instanz bereits vorhanden | Validierte Ansible-Projekte, Inventory, Test-/Deployment-Jobs, eng begrenzte Proxmox-API |
| Git-Versionsverwaltung | z. B. CT 1002 (Forgejo LTS) | Für vollständig autonome lokale Plattform; sonst als austauschbarer bestehender Git-Dienst | Repositories, Prompt-Versionen, Änderungen und Review-Historie |
| Coding-Agent / Sandbox | z. B. CT 1003, ggf. isolierte VM | Für promptbasierte Generierung | Modellzugang, generiertes Ansible ausschließlich in isolierter Branch-/PR-Umgebung, **keine Hypervisor-Credentials** |
| Modellinferenz | bedingt separater LXC/VM | Nur wenn kein bereits verfügbarer, autorisierter Modellendpunkt existiert | Lokale/offline Modell-API; bei GPU-/Kernel-/SELinux-Anforderungen VM bevorzugt |
| CI-Test-Runner | isolierte Job-Umgebung, ggf. weiterer Gast | Vor produktiven generierten Deployments | Syntax, ansible-lint, Idempotenz-/Integrationstests; keine privilegierten Deploy-Secrets |

Die obigen VMIDs sind **Beispiele**, keine festen Vorgaben. Proxmox-Inventar
und definierter VMID-Bereich bestimmen die freien Nummern. Aus den Rollen folgt
nicht zwingend eine starre Anzahl LXC: vorhandene autorisierte Dienste dürfen
als vorhandene Abhängigkeiten gewählt werden. **Nur belegbar benötigte Gäste
anlegen**, niemals die gesamte spätere Dienstepalette vorsorglich.

Rocky Linux als unterstützte Standard-LXC-Distribution und unprivilegierte
Container sind vorzuziehen. Anforderungen an Kernel, GPU-Zugriff, SELinux oder
Isolation können eine VM statt LXC erforderlich machen; das muss der Plan
sichtbar begründen.

## 3. Erforderliche Fragen in der WebApp

- **Proxmox:** API-Endpunkt/Fingerprint, Cluster-/Node-Auswahl, freier VMID-
  Bereich, geeigneter RootFS-Storage, für Gäste erreichbare Bridge/VLANs,
  Ressourcenbudget, Templates und OS-/CPU-Kompatibilität.
- **Netzwerk:** Netzwerkrolle nach Betreiberwissen, DNS/DHCP-Herkunft,
  Domäne/Hostname-Präfix, Routing, internes Zertifikats-/TLS-Konzept.
- **Git:** lokales Forgejo neu bereitstellen oder **bestehenden** Git-Dienst
  verwenden; Repo-Struktur und Schreib-/Review-Policy.
- **KI:** lokaler Modellserver neu erstellen oder erreichbaren vorhandenen
  Endpunkt verwenden; Hardware-/RAM-/GPU-Budget; kein Anbieterzwang.
- **Ansible:** gewünschte Rolle/Scope für API-Token, Inventory-Ziele,
  Versions- und Testpolicy, separate Berechtigung für Deployments.
- **Backup/Recovery:** Backup-Ziel und Restore-Anforderungen erfassen;
  nach Erstellung der Steuerungsebene als Schutzpflicht umsetzen, jedoch
  kein Recovery-Paket als Voraussetzung für eine **Neuinstallation** verkaufen.

Jeder automatisch vorgeschlagene Wert erhält `source` (z. B. DHCP-Lease,
Proxmox-API, Bedienereingabe), `verified` und ggf. `warning`. Zugangsdaten,
Tokens und Keys gelangen nicht in öffentliche Git-Repositories, URLs oder
KI-Prompts. Sensible Konfiguration separat geschützt speichern.

## 4. Zwei getrennte Ausführungsphasen

### Phase A – Einmaliger Infrastruktur-Bootstrap

Der bereits vorhandene Stage-0-LXC kann nicht ohne explizit eingerichtete
Berechtigungen neue Proxmox-Gäste erzeugen. Daher wird einmalig ein
**minimal berechtigter, widerrufbarer Bootstrap-Ausführungskanal** benötigt,
der die freigegebenen Gäste erstellen darf. Ein vorgeschlagener Umsetzungsweg:

- Read-only Discovery zunächst per getrennter Proxmox-API-Identität;
  Schreib-Identität niemals implizit aus Lesezugang ableiten.
- Erst nach konkret angezeigtem Plan und Betreiberfreigabe kurzlebiges,
  auf Nodes/Pools/Storages/VMIDs nach Möglichkeit eingeschränktes Token
  bereitstellen. Proxmox hat feingranulare Rechte; die tatsächlich
  benötigten API-Operationen und die minimale Rollenmenge **vorher**
  gegen die verwendete PVE-Version testen. Aktionen, die besondere
  Berechtigungen erfordern, ggf. ausdrücklich separat freigeben.
- Bootstrap-Executor führt **festgelegte, versionierte** Proxmox-Aufgaben
  für benötigte LXC/VMs aus, keine vom Modell generierten Shell-Befehle.
- Je Gast: Reservierung/Kollision, Vorprüfung, `create`, `start`,
  Netzwerk/DNS/SSH, Paket-/Dienst-Healthcheck, nachvollziehbarer Status.
- Fehler stoppen weitere Änderungen; nie bestehende fremde Gäste löschen.
  Resume-Protokoll und idempotente Wiederaufnahme statt blindem Retry.
- Danach Bootstrap-Token auf notwendigen Scope reduzieren oder widerrufen;
  reguläre Deployments laufen aus getrennten Ansible-Jobs.

### Phase B – Promptgesteuerter Plattformaufbau

Versionierte Prompt-Vorlagen mit änderbaren Parametern:
1. Nutzer wählt einen Blueprint und passt sein Ziel an.
2. UI erzeugt eine *begrenzte* Task-Spezifikation mit eingesetzten
   Site-Daten, Anforderungen, erlaubten Zielgruppen und Akzeptanztests.
3. Coding-Agent erhält **keine Deploy-Tokens** und erstellt Ansible-Rollen,
   Playbooks, Tests und Dokumentation in einem Feature-Branch.
4. CI prüft Schema/YAML, Ansible-Syntax, Lint, Berechtigungen, Seiteneffekte,
   mögliche Secret-Leaks; Ansible `--check` und `--diff`, soweit von den
   konkreten Modulen unterstützt (Check-Mode ist keine Erfolgszusage).
5. Die WebApp zeigt Diff, betroffene LXCs/Hosts, Risiko und geplante
   Änderungen. Menschliche Freigabe für die konkrete Revision und Ziele.
6. Deployment-Controller führt nur diese freigegebene Revision über
   allowlist-basierte Ansible-Entry-Points aus.
7. Resultate, Abweichungen, Wiederanlauf/Restore-Gates werden protokolliert.

**Prompt-Beispiel (anpassbar):**
> Stelle einen eigenständigen BookStack-Dienst mit internem TLS, OIDC,
> Rollen- und Backup-Konzept bereit. Verwende die lokalen Site-Vorgaben,
> lege einen separaten Gast an, erzeuge Ansible-Rollen samt Tests und
> präsentiere vor Deployment einen überprüfbaren Plan.

Dieses Beispiel **beschreibt nur einen beabsichtigten Blueprint**. Die
Freigabe gilt niemals pauschal für beliebige zukünftige Prompt-Ausgaben.

## 5. Minimaler Web-Installationspfad

`Neuinstallation`
→ Grundkonfiguration (site.local)
→ Proxmox-Discovery und Ressourcenprüfung
→ Git-/KI-/Deployment-Betriebsmodus auswählen
→ erforderliche Infrastruktur-Gäste berechnen
→ versionierten Plan mit VMIDs, Zielnets, Ressourcen, Rechten, Tasks anzeigen
→ **separate** Freigabe Infrastruktur-Bootstrap
→ kontrollierte Proxmox-API-Bereitstellung
→ Dienst-Healthchecks und Rollen-/API-Verifikation
→ Prompt-/Blueprint-Katalog
→ Branch, Ansible, Test, Review
→ **separate** Freigabe Plattform-Deployment
→ Verifikation und Betriebs-/Backup-/Restore-Nachweis.

`Wiederherstellen` ist ein **separater Einstiegszweig**, wenn zuvor eine
Installation vorhanden war. Ein optionaler Recovery-Export bleibt im Menü
»Werkzeuge«, nicht auf dem Hauptpfad.

## 6. Durchgängiger Bootstrap-Handoff und bedarfsabhängige Topologie

**Verbindlicher Nutzerablauf:** Einmaliges Bootstrap auf dem Proxmox-Host
erstellt CT 1000 und liefert die HTTPS-Webadresse. Ab dann erfolgt die
weitere Neuinstallation vollständig über CT 1000: Site-Parameter erfassen,
Discovery durchführen, den geplanten Minimalbestand an Gästen zeigen,
**genau diesen Bestand einmalig bestätigen**, alle genehmigten Gäste
installieren und die Ergebnisse/Fehler/Wiederaufnahme in der WebApp anzeigen.

Der initiale Shellprozess wartet **nicht** über die gesamte Browser-Sitzung
hinweg; er beendet sich nach Stage 0. Ein persistenter Jobstatus in CT 1000
und eine eng berechtigte, ausdrücklich autorisierte Proxmox-
Bootstrap-Identität gewährleisten die kontrollierte Fortsetzung.

**Provisionierungsabfolge**:
1. WebApp: read-only Proxmox-Discovery (VMIDs, Ressourcen, Storage,
   Templates, Bridges, DNS- und DHCP-Herkunft).
2. WebApp: Moduswahl für Git (bestehend/neu), Coding-Agent (lokal/extern),
   Inferenz (existierender API-Endpunkt/lokaler Gast) und CI-Isolation.
3. Plan-Compiler: berechnet eine **Minimal-Topologie** mit nachvollziehbaren
   Abhängigkeiten; prüft freie Ressourcen und ggf. nötige Linux-VM statt LXC.
4. Einmalige Operatorfreigabe für die exakte Planrevision und erlaubten
   Ziele/Aktionen. Spätere Planänderungen erfordern eine neue Freigabe.
5. Bootstrap-Executor: erzeugt 1001 und richtet DNS/Netzwerk sowie Ansible
   ein; **erst nach erfolgreicher lokaler Ansible- und Connectivity-Prüfung**
   schaltet der Ablauf auf Controller-Provisionierung um.
6. Controller 1001: installiert die **im bestätigten Plan** enthaltenen
   weiteren benötigten Git-/Agent-/CI-/Modell-Gäste automatisiert über
   eingeschränkte Ansible-/Proxmox-API-Operationen. Keine weiteren
   Freigabedialoge für bereits genehmigte einzelne Aktionen, aber
   harte Grenzen für VMIDs, Netze, Images, Ressourcen und Task-Arten.
7. Healthchecks, eventuelle Fehler und sichere Wiederaufnahme bleiben
   in CT 1000 sichtbar; keine stillen Containerlöschungen oder
   Entsperrung unautorisierter Maßnahmen.
8. Das Ergebnis ist die minimal einsatzfähige Prompt-/Git-/Ansible-
   Plattform. Weitere promptgenerierte Deployments benötigen **eine
   eigene Review- und Freigabegrenze** pro Änderungsrevision.

**Wann sind CT 1002–1004 nötig?** Nicht pauschal. Die Rollen sind
konfigurierbar und die VMIDs dynamisch:
- Git/Forgejo-LXC nur, wenn kein zugelassener vorhandener Git-Dienst
  genutzt werden soll und die selbstständige lokale GitOps-Plattform
  benötigt wird.
- Agent-/Sandbox-Gast, wenn lokale Prompt→Ansible-Codegenerierung Teil des
  gewählten Installationsmodus ist; Sicherheitsgrenzen können stattdessen
  eine isolierte VM verlangen.
- Inferenz-Gast nur bei gewünschter lokaler Inferenz **und** fehlendem
  autorisierten passenden Modell-Endpunkt; CPU/RAM/GPU-Fähigkeiten
  entscheiden über VM/LXC und Ressourcen.
- Separater CI-Runner/Job-Gast je nach Isolation, Anzahl paralleler
  Tests und vorhandenem Runner; kein gemeinsamer privilegierter
  Agent-/Deploy-Kontext.

**Kein Blankoscheck:** »Ohne weitere Aufforderung« bedeutet
*innerhalb der vorher freigegebenen Topologie* automatisch installieren,
nicht beliebige neue LXCs anlegen. Die WebApp und der Coding-Agent
erhalten keinen generellen Proxmox-root-Zugang. Neuplanung oder
Zielerweiterung erfordern eine neue Betreiberfreigabe.

**Realtest-Hinweis:** CT 1001 wurde auf dem Test-Proxmox erstellt, aber
der Paketdownload scheiterte zunächst an DNS. Ein idempotenter Resume
mit korrekt aus den Site-Daten übernommener DNS-Konfiguration ist
Voraussetzung für den späteren automatischen Handoff. Bestehenden
CT 1001 **nicht** durch erneutes `pct create` überschreiben.

## 7. Erster umsetzbarer Bereitstellungsschritt (Entwicklung)

`bootstrap/deploy-ansible-controller.sh` ist ein **ausführbarer,
eng eingegrenzter Host-Bootstrap** für den ersten Ansible-Controller-Gast.
Er läuft explizit auf dem Proxmox-Host, nicht im unprivilegierten Setup-LXC.
Das ist eine bewusste Zwischenstufe, **noch nicht** das spätere
vollständig webgesteuerte Deployment. Der Befehl erfordert eine
Betreiberentscheidung und einen zweiten wortgetreuen Bestätigungsschritt.

### Vorbereitung / read-only Plan

Auf dem Proxmox-Host, nach Prüfung des Branch-Commits:

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash -n /root/tobe4home-bootstrap/bootstrap/deploy-ansible-controller.sh
sudo bash /root/tobe4home-bootstrap/bootstrap/deploy-ansible-controller.sh \
  --bridge=<betreibergeprüfte-bridge> --storage=<rootdir-storage>
```

Der Plan nutzt den bereits offiziell geladenen Rocky-10-LXC-Template-Namen
und prüft vor jeder Änderung u. a. VMID 1001 clusterweit, ZFS-/Storage-
Restbestände, aktives RootFS-Storage, Host-Bridge sowie unprivilegierte
UID/GID-Zuordnung. Der Operator entscheidet ausdrücklich über
`--apply` und die exakte Eingabe `DEPLOY 1001`.

### Fehlgeschlagener Paketdownload nach erfolgreichem CT-Create

Der erste reale Stage-1-Versuch auf dem Test-Proxmox zeigte:

- `pct create 1001` und `pct start 1001`: **erfolgreich**.
- `dnf install`: **abgebrochen**, weil der neue Gast
  `mirrors.rockylinux.org` nicht auflösen konnte.
- VMID 1001 bleibt vorhanden. **Niemals** den Create-Installer mit
  `--apply` erneut starten oder den CT aus diesem Grund löschen.

Proxmox kann bei LXC den Host-DNS-Resolver übernehmen, selbst wenn die
Gast-IP per DHCP bezogen wird. Das Setup hat bereits einen bearbeitbaren,
nach Herkunft gekennzeichneten DNS-Resolver gespeichert. Der
Create-Installer übergibt diesen jetzt explizit als `--nameserver`.
Er prüft die Namensauflösung **vor** dem Paketdownload.

Für den bereits existierenden CT bietet
`bootstrap/resume-ansible-controller.sh` einen strikt begrenzten
Wiederaufnahmepfad. Ohne `--apply` liest er nur die Konfiguration,
den gespeicherten DNS aus CT 1000, die effektive `resolv.conf`,
Gast-Routen und eine DNS-Testabfrage. Wenn die DNS-Auflösung fehlschlägt,
kann der Betreiber **nach separater Freigabe** ausschließlich CT 1001
auf den ausgewählten Resolver umstellen, den CT gezielt neu starten
und die fehlende Paketinstallation nach erfolgreichem DNS-Test nachholen.
Es erfolgen keine Änderungen an CT 1000, anderen Gästen, am Proxmox-Host-
DNS, an Switches oder Firewall-Regeln. Ein DNS-Override ist per
`--nameserver=<geprüfte-IP>` möglich.

```bash
sudo git -C /root/tobe4home-bootstrap pull --ff-only
sudo bash /root/tobe4home-bootstrap/bootstrap/resume-ansible-controller.sh \
  --bridge=vmbr3
# Erst nach Kontrolle des read-only-Plans:
sudo bash /root/tobe4home-bootstrap/bootstrap/resume-ansible-controller.sh \
  --bridge=vmbr3 --apply
# Freigabe: RESUME 1001
```

Die tatsächliche lokale Bridge kann abweichen; sie muss mit der
vorhandenen CT-Konfiguration übereinstimmen. Die Stage-0-DNS-Einstellung
muss zuvor als **tatsächlich erreichbarer Resolver** validiert werden.
Falls DNS nach der gezielten Umstellung weiter fehlschlägt, stoppt die
Wiederaufnahme ohne DNF-Installation und bewahrt den Zustand zur Diagnose.
Ungeprüft Nesting oder privilegierte LXC-Rechte zu aktivieren ist kein
DNS-Fix. Die Warnung zu systemd 257 ist separat zu bewerten.

### Ausführung und Abnahme

```bash
sudo bash /root/tobe4home-bootstrap/bootstrap/deploy-ansible-controller.sh \
  --bridge=<betreibergeprüfte-bridge> --storage=<rootdir-storage> --apply
sudo pct config 1001
sudo pct exec 1001 -- ansible --version
```

Die Anwendung erstellt ausschließlich CT 1001 mit Proxmox-`pct create`,
startet den neuen Container und installiert `ansible-core`, `git`,
OpenSSH und Python. **Kein Restore, kein automatisches Löschen, kein
Zugriff auf bestehende Container und keine Installation von Forgejo.**
Bei Fehlern bleibt der Teilzustand zur Diagnose stehen und ein erneuter
Versuch wird blockiert, statt vorhandene Volumes zu überschreiben.
Die Freigabe erfolgt auf dem Proxmox-Terminal, nicht über die WebApp.

Die WebApp verlinkt vom Installationsplan auf einen konkreten
Infrastruktur-Bereitstellungsbildschirm; noch ohne Schreibzugriff auf
Proxmox. Als **nächster** Schritt wird ein begrenzt berechtigter, explizit
autorisierter Proxmox-API-Executor für echte Webfreigaben benötigt.
Keine API-Tokens im öffentlichen Repository, keine `root@pam`-Tokens
und keine generierten Agentenbefehle unmittelbar am Hypervisor ausführen.

## 8. Liefergates (noch offen)

- [ ] Formulare / versioniertes Schema für alle tatsächlich benötigten
      Infrastrukturrollen und Modi; keine fest codierten lokalen Netzdaten.
- [ ] Rein lesender Proxmox-Discovery-Adapter (explizit eingerichtete
      API-Identität; kein Host-root im Web-Dienst).
- [ ] Minimal-LXC-Plan-Compiler mit OS/Template/Storage/VMID/Netz-Prüfungen,
      Kosten/RAM und voraussichtlichen Berechtigungen.
- [ ] Genehmigung und reproduzierbarer Stage-1-Provisioner; negative
      Berechtigungs- und Fremdressourcen-Tests.
- [ ] Isolierte Ansible-/Git-/Coding-Agent-Einheiten mit klaren
      Schlüssel-/Token-Grenzen und durchlaufenden Gesundheitsprüfungen.
- [ ] Prompt- und Blueprint-Vorlagen, Ansible-Codegenerierung in Git-Branches,
      Review/CI, freigegebener Jobrunner und Web-Statusverfolgung.
- [ ] Unabhängige Backups, tatsächlicher Restore, Ausfall des Git-/KI-Servers
      sowie Wiederanlauf des Orchestrators getestet.
- [ ] Für Produktionsfreigabe: Security, TLS, OIDC, Offline-Notfallverfahren,
      Secrets-Rotation und idempotente Neuinstallation abgenommen.

**Aktueller Stand:** Stage-0 funktioniert auf einem realen Proxmox-LXC.
Der Web-Wizard erfasst lokale Angaben, zeigt einen Plan und kann ein
optionales ZIP exportieren. **Er provisioniert noch keine weiteren
LXC/VMs, installiert noch kein Ansible/Git/Agent und führt noch keine
promptgesteuerten Deployments aus.** Diese Aufgaben sind die nächste
eigentliche Implementierung – nicht weitere Recovery-Exports.
