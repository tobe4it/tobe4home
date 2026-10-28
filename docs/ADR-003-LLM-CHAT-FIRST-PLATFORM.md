# ADR-003 – KI-Chat ist die primäre tobe4home-Benutzeroberfläche

Status: **Produktziel konkretisiert am 28.10.2026; Entwurf, noch nicht implementiert.**

## Produktversprechen

tobe4home ist ein **sprachgesteuerter, selbst gehosteter Familien-IT-Administrator**.
Eine fachfremde Person soll mit einer LLM in einem Chat sprechen können:

- „Installiere Paperless für unsere Familie; private Dokumente bleiben privat.“
- „Richte einen DNS-Filter für unser Heimnetz ein, aber zerstöre den vorhandenen DNS nicht.“
- „Wir möchten einen filternden Webproxy mit nachvollziehbaren Regeln.“
- „Stelle einen Mailserver für unsere Domain bereit, mit TLS, Spam- und Backupschutz.“

Der Chat ist die **primäre Interaktion**; Formularfelder sind optionale
kompakte Eingabe- und Freigabekontrollen für wenige tatsächlich fehlende
Informationen. **AnsibleForms 7 und das zugehörige RTE bleiben unterstützende
Workflow- und Ansible-Ausführungsschicht im Hintergrund, nicht das
eigentliche Benutzerprodukt.** Das aktuell implementierte Vorschauformular ist
eine **Übergangslösung**, kein Ersatz für die Chatoberfläche.

## Installation und Betrieb

1. Ausgangspunkt ist ein **vorhandener Proxmox-VE-Host**.
2. Das bestätigte, begrenzte Host-Bootstrap erstellt genau den
   **unprivilegierten Rocky Linux 10 Controller CT1001**.
   Es gibt keinen CT1000, keinen zweiten obligatorischen Controller.
3. Der Controller hostet die Chat-App, eine LLM-Anbindung, den deterministischen
   Planner, die Validierung, den Freigabedienst und AnsibleForms/RTE.
4. Für die LLM wird ein freigegebener vorhandener oder neu bereitgestellter
   Inferenz-Endpunkt verwendet; keine Pflicht-GPU und kein obligatorischer
   weiterer Container. Nur begründet benötigte Dienste erzeugen weitere Gäste.
5. LTS/RHEL-kompatible Images und unprivilegierte LXC werden vorgezogen;
   VM nur bei fachlich begründeter Ausnahme. Native systemd-/RPM-Installation
   oder rootless Podman, sofern innerhalb der LXC-Sicherheitsgrenzen erprobt.

## Pipeline: Chat → geprüfte Änderung

```text
Nutzer: natürliche Sprache
  ↓
LLM: Ziel, Anforderungen, Rückfragen, kompatible Service-Blueprints
  ↓
Read-only Discovery: Proxmox, Ressourcen, Netze, DNS, bestehende Dienste
  ↓
Deterministische Planspezifikation (schema-validiert; belegte Fakten
mit Herkunft, Prüfniveau und Zeitstempel)
  ↓
Ausgewählter geprüfter Blueprint ODER isolierter Coding-Agent:
Ansible-Rollen/Playbooks, OpenTofu-Konfiguration, Tests, Dokumentation
im nachvollziehbaren Git-Branch/PR
  ↓
CI: Schema, Ansible-Syntax, ansible-lint, policy-as-code,
Secret-Scanning, Sicherheits-/Idempotenz-/Integrationsprüfungen
  ↓
Maschinenlesbarer Plan + verständliche Änderungsvorschau:
neue Gäste, VMIDs, Bridge, Storage, Ports, Abhängigkeiten,
DNS-Einträge, TLS, Firewall, Backup, Migration, Risiken
  ↓
Bewusste Freigabe DER KONKRETEN Revision und exakt benannten Ziele
  ↓
Privilegientrennender Executor (nicht LLM, nicht beliebige Chat-Ausgabe):
Proxmox-API / OpenTofu → Gaststart → AnsibleForms RTE / Ansible
  ↓
Healthchecks, negatives ACL-/Sicherheitstesting, Rollback- bzw.
Resume-Strategie, vollständiger Audit-Nachweis mit Task-Laufzeiten
  ↓
Chat: „Eingerichtet; hier ist der Nachweis“ oder begrenzter Fehlerbericht
```

## Was die LLM darf und nicht darf

Die LLM **darf** Servicewünsche verstehen, relevante Rückfragen stellen,
bereits vorhandene Infrastruktur aus *berechtigten* Discovery-Daten
berücksichtigen, Alternativen begründen und **neue Ansible-Artefakte
erzeugen**. Sie ist nicht auf einen starren Servicekatalog beschränkt:
Für unbekannte Services ist ein isolierter Agenten-/PR-/Testweg vorgesehen.

Die LLM erhält **keinen** Proxmox-Root-Zugang, keinen allgemeinen SSH-Key,
keine produktiven Ansible-Deploy-Tokens und keinen direkten Zugriff auf
Familiengeheimnisse. Modelltext wird niemals ungeprüft mit `shell`,
`command`, `pct`, `qm`, `pvesh` oder OpenTofu apply auf dem Host
ausgeführt. Auch der AnsibleForms-RTE startet nur zuvor freigegebene,
versionierte und auf ein Ziel begrenzte Änderungen.

Unbekannter generierter Code ist bis nach Tests und individueller Freigabe
**nicht vertrauenswürdig**. Ein freigegebener Blueprint kann schneller
bereitgestellt werden, muss aber weiterhin die konkreten Host- und
Änderungsgrenzen prüfen. Freigaben gelten nicht dauerhaft für beliebige
spätere Promptänderungen.

## Dienstspezifische Regeln

**Paperless:** dedizierter Gast, document-scoped Rechte auch in AI-Chat/RAG,
OIDC/Benutzer- und Eltern-/Kindergrenzen, Storage, Importsicherung,
Backup und geprüftes Wiederherstellen. Persönliche Dokumente werden
niemals als ungefilterter Prompt-Kontext an das Modell gegeben.

**DNS-Filter:** bestehende Resolver, DHCP-, DNSSEC-/Split-DNS-, Port-53-
und Ausfallkonzepte erkennen; insbesondere vorhandene Pi-hole-/Unbound-
Instanzen nicht ungefragt ersetzen. Migrations-, Cache- und
Fallback-Verhalten sichtbar freigeben.

**Filternder Proxy:** ausdrücklich zwischen Reverse Proxy, Forward Proxy,
DNS-Inhaltsfilter und TLS-Inspektion unterscheiden. Kein stilles MITM,
kein eigenmächtiges Trust-Root-Zertifikat und kein offener Proxy.

**Mailserver:** Domain und DNS-Verwaltung, öffentliche Zustellbarkeit,
MX, SPF, DKIM, DMARC, PTR, TLS, Speicher, Spamfilter, Abuse-/Backupschutz
und bestehende Mailserver prüfen. Falls technische oder administrative
Voraussetzungen fehlen, keine irreführende „funktionsfähige“ Installation
behaupten.

Jeder Dienst besitzt einen versionierten Akzeptanzvertrag (Ports,
Abhängigkeiten, Healthchecks, Backup/Restore, Upgrade-/Security-Lebenszyklus).

## Abgrenzung zum Ist-Zustand

**Bereits real nachgewiesen:** CT1001 mit AnsibleForms/RTE, HTTPS,
read-only hostseitige Proxmox-Gastzählung, Transfer in den RTE,
Vorschau-Playbook mit `ok=6 changed=0 failed=0`
(28.10.2026, 21 LXC ohne Controller, 0 VMs).

**Nicht implementiert:** primäre Chat-App und LLM-Anbindung,
standortspezifische Bestandsaufnahme aus CT1001 über eine eingeschränkte
Proxmox-API, KI-gestützte Codegenerierung, Git-/CI-Gate, Planfreigabe,
Proxmox-Schreibberechtigungen, eigentliche Gast- und Dienstbereitstellung.

## Umsetzung in Etappen

1. **Chat-MVP**: eigener tobe4home-Chat als Startseite in CT1001.
   Eine vorhandene Modell-API genügt zum Test. Chat darf nur lesen/
   planen; zuverlässige strukturierte Service-Spezifikation.
2. **Erste Service-Blue­prints**: Paperless und DNS-Filter mit
   reproduzierbaren, geprüften Rollen und automatisierten Tests;
   Proxy und Mail als eigene komplexere Serviceverträge.
3. **API-Discovery und Plan-Compiler**: tatsächliche Bestände aus dem
   Controller, isoliert lesendes Token und TLS-Verifikation.
4. **PR-/CI-Codegen**: Sandbox mit begrenztem Repository-Zugriff,
   ohne Deploy-Secrets. Nutzer kann generierten Plan, Diff und Tests sehen.
5. **Genehmigter Executor**: definierte neue VMIDs/Services auf erlaubten
   Ressourcen; negative Rechte-Tests für CT1001 und Altbestände.
6. **End-to-End-Abnahme**: „Richte DNS-Filter ein“ → Konfiguration →
   Plan/Freigabe → neuer Dienst → Prüfung → Audit → Chatantwort.
   Danach Paperless, Proxy und Mail aufsteigend nach Kritikalität.

Die Pipeline muss ohne zusätzliche Auswahl „Ist Proxmox vorhanden?“ oder
„Laufen schon Dienste?“ auskommen: **erkennen statt erfragen**.
Daten, die technisch nicht zuverlässig erkennbar sind, werden als
explizite Entscheidungen mit Unsicherheit gekennzeichnet.
