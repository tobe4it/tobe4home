# tobe4home: nächster Bootstrap – Dienstplanung (CT1001)

Stand: 28.10.2026. Ausschließlich Entwicklungszweig, nicht als stabile
Veröffentlichung oder durchgeführter Live-Test zu verstehen.

## Ziel und Grenzen

Im bestehenden, bereits lauffähigen, unprivilegierten Rocky-Linux-10-CT1001
(`tb4h-controller`) kommt das AnsibleForms-Formular
**tobe4home Dienstplanung** hinzu. Es nimmt einen deutschsprachigen
Freitextauftrag und ein explizites Dienstprofil entgegen:

- Paperless / Dokumentenverwaltung
- DNS-Filter / Pi-hole
- Filternder Web- oder Reverse-Proxy
- Mailserver

Das RTE-Playbook validiert den Input, liest die vorhandene, anonymisierte
Proxmox-Momentaufnahme aus seinem übertragenen Playbook-Verzeichnis und
liefert **nur eine gesperrte Ansible-Vorlage**. Im Ergebnis erscheint
ausschließlich der SHA-256-Fingerprint des Freitextauftrags, nicht der
Auftragstext selbst. Der AnsibleForms-Server kann Eingaben unabhängig davon
in seinen Jobdaten verarbeiten: niemals Passwörter, interne Netzadressen,
Tokens oder personenbezogene Dokumente im Formular eingeben.

**Noch nicht integriert:** LLM/KI-Chat, Modelllaufzeit, fortlaufender
Chat-Verlauf, automatische Interpretation des Auftrags, versionierte
Playbook-Generierung, Test-Gateway, Proxmox-API, OpenTofu oder Deployment.
Die Vorlage enthält absichtlich einen `ansible.builtin.fail`-Stopper;
sie ist keine lauffähige Dienstbereitstellung. Bestehende Git-Rollen sind
nur Referenzen, keine automatisch autorisierten Installationsbausteine.

## Nachrüstung auf dem vorhandenen Proxmox-Host

Diese Befehle laufen auf dem **Proxmox-Host**, nicht in CT1001:

```bash
cd /root/tobe4home-bootstrap
git switch feat/bootstrap-setup-wizard-20261027
git pull --ff-only

# Nur lesende Vorprüfung – keine neue Gastanlage:
sudo bash bootstrap/deploy-service-planner-1001.sh

# Separater, ausdrücklich bestätigter Formular-Import:
sudo bash bootstrap/deploy-service-planner-1001.sh --apply
```

Nur bei `--apply` wird die exakte Bestätigung `PLAN 1001` verlangt.
Danach werden **ausschließlich** diese neuen Dateien in das
AnsibleForms-Datenverzeichnis übertragen:

```text
/opt/ansibleforms/data/forms/tobe4home-service-plan.yml
/opt/ansibleforms/data/playbooks/tb4h-service-plan-preview.yml
```

Die bisherige `tobe4home Start`-Maske, das bestehende RTE,
MariaDB, Initialkennwort und andere Proxmox-Gäste bleiben erhalten.
Bereits vorhandene, lokal geänderte gleichnamige Dateien werden nicht
überschrieben. Ausschließlich die AnsibleForms-WebApp wird zum Laden des
neuen Formulars neu gestartet (kurze Unterbrechung möglich).

Die Einrichtungs-URL des Planers erscheint **erst nach**
AnsibleForms-/RTE-Service- und HTTPS-Healthcheck im Terminal:

```text
https://<aktuelle-CT1001-IP>/form/tobe4home-dienstplanung
```

Der Anmeldungsschritt verwendet das bestehende AnsibleForms-Konto.
Es werden keine neuen Credentials erzeugt oder angezeigt.

## Akzeptanzprüfung

1. Read-only-Vorschau zeigt `PREVIEW_ONLY=YES`.
2. `--apply` wird nur auf dem verifizierten CT1001 nach `PLAN 1001`
   angenommen und endet mit `TOBE4HOME_PLANNER_READY=YES`.
3. Im Browser ist das deutschsprachige Formular sichtbar und akzeptiert
   einen Beispielauftrag für eines der vier Profile.
4. Im RTE-Job stehen `ENTWURF – KEINE BEREITSTELLUNG`,
   die LXC-/VM-Zahlen der Bestandsaufnahme und
   `LLM ... NICHT ANGEBUNDEN`.
5. Kein Task ist `changed`, und es gibt keine Änderungen an
   bestehenden Diensten oder Gästen. Vor echten Deployments fehlen
   Datensicherung, Berechtigungsprüfung und eigene Freigabegates.

## Nächster technischer Schritt

Separates lokales, zunächst nur lesendes Modell-/Provider-Gateway und
KI-Dialog. Modellantworten dürfen ausschließlich ein streng validiertes
Planungsformat liefern; sie dürfen keine Shell-Kommandos,
Ansible-Tasks oder Proxmox-Befehle direkt ausführen. Ein gesonderter
Git-/Test-/Review-/Approval-Gateway erzeugt erst anschließend
versionierte, geprüfte Playbooks.
