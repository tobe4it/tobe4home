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

## 6. Liefergates (noch offen)

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
