# Paperless-Mailablage auf bergen-mail – Entwurf / kein Produktiv-Cutover

## Implementierungsstand: 31.10.2026, Draft PR #5

**Codephase 1 im Entwicklungsbranch `feat/paperless-mail-intake` umgesetzt, produktiv nicht aktiviert.**

Die Ansible-Mailrolle kann nach ausdrücklichem Opt-in zwei feste Scan-Empfängeradressen auf die Plusadressen `paperless+familie` / `paperless+eltern` umschreiben. Dovecot 2.4/LMTP und ein ausschließlich für das technische Paperless-Mailkonto bereitgestelltes Sieve-Skript ordnen die Envelope-Details den bestehenden Zielnamen `Familie/Eingang` und `Eltern/Eingang` zu. Unbekannte Details bleiben im technischen `INBOX`. Der Mailbox-Teil erzeugt die 25 Eltern-/Familien-/Privat-Ordner nur, wenn sie noch fehlen; bestehende Dokumente und Mails werden nicht gelöscht oder verschoben. Ein vorhandenes nicht durch die Rolle verwaltetes Sieve-Skript wird nicht überschrieben.

**Noch nicht umgesetzt und deshalb nicht freigegeben:** Dovecot-Shared-IMAP-Namespace/ACL, tatsächliche Scanner-Anbindung, produktive LDAP-Kontoanlage, End-to-End-Postfix→LMTP→IMAP-Zustellung, Paperless-E-Mail-Regeln und Paperless-Dokumentrechte, automatisches Aufräumen. Die Sieve-Erweiterung darf nicht aktiviert werden, solange andere Benutzer-Sieve-Skripte vorhanden und ungeprüft sind.

Die Änderungen sind standardmäßig inaktiv (`mail_backend_paperless_intake_enabled: false`) und bewusst ein **Draft**. Der Code ist ohne Zugang zum laufenden Bergen-Mailserver erstellt und benötigt eine reale Ansible-/Dovecot-Prüfung vor jeder Produktivfreigabe.

### Prüfschritte auf dem Controller, ohne Produktivänderung

1. Unveränderte standortspezifische Variablen `ansible/group_vars/all/bergen-mail.yml` und Vault gegen die aktive Hostkonfiguration prüfen; `mail_backend_paperless_scan_domain: thebergens.net` nur **nach** Bestätigung als tatsächlich bediente Domäne setzen. Das Audit benötigt die Scan-Domäne, aber **nicht** `mail_backend_paperless_intake_enabled: true`.
2. Offline-Contract-Tests und Ansible-Syntax prüfen:

   ```bash
   python3 -m unittest discover -s tests -p 'test_paperless_mail_intake_contract.py'
   ansible-playbook --syntax-check \
     -i ansible/inventory.yml -i ansible/inventory.local.yml \
     -e @ansible/group_vars/all/bergen-mail.yml \
     ansible/playbooks/audit-paperless-mail-intake-readonly.yml
   ```

3. Nur lesendes Infrastruktur-Audit ausführen:

   ```bash
   ansible-playbook \
     -i ansible/inventory.yml -i ansible/inventory.local.yml \
     -e @ansible/group_vars/all/bergen-mail.yml \
     ansible/playbooks/audit-paperless-mail-intake-readonly.yml \
     --ask-vault-pass
   ```

4. Technisches LDAP-Konto `paperless` und die tatsächlichen `Mailuser`-Rechte gegen Dovecot und Synology prüfen. Vor `mail_backend_paperless_intake_enabled: true` ein überprüft wiederherstellbares Mail-Backup nachweisen.
5. Nach gesonderter Aktivierungsfreigabe die bestehende Mail-Backend-Rolle verwenden; *kein* zusätzlicher öffentlicher MX, keine DNS-Änderung und keine Umstellung der bestehenden Scan-Quelle. Reale E-Mails erst nach erfolgreicher Empfänger-, ACL- und Paperless-Workflow-Abnahme senden.

**Definition of Done für die Codephase 1:** Syntax-/Contract-Tests bestanden, LDAP-Servicekonto verifiziert, beide Aliase `postmap -q` korrekt, Dovecot und Sieve verifiziert, plusadressierte SMTP/LMTP-Testnachricht je Bereich im richtigen Ordner angekommen, unbekannte/abgewiesene Empfänger korrekt behandelt, keinerlei Änderung an den übrigen Benutzerpostfächern.


Stand: 2026-10-31. Zielplattform: bestehender `bergen-mail`-LXC mit Postfix und Dovecot 2.4, bestehendes Paperless-ngx. Dieses Dokument beschreibt den gewünschten Sollzustand; der neue Branch erzeugt **noch keine** LDAP-Identitäten, Mailboxen, ACLs oder Paperless-Regeln.

## Zweck und bestehende Grenzen

- Papier- und Mailimport über Paperless führen in identische Berechtigungsbereiche `Privat/<user>`, `Eltern`, `Familie`, aber **nicht** in einen gemeinsamen, ungeschützten Dokumentenbestand.
- Die vier Mailuser sind `thomas`, `nadja`, `nils`, `linda`. LDAP-`Mailuser` bleibt Quelle für Postfächer. Berechtigungsquelle für Eltern/Familie bleibt LDAP; statische ACLs dürfen nur aus geprüfter Gruppenmitgliedschaft abgeleitet werden.
- Der vorhandene Quellscan-/NAS-Import einschließlich des noch nicht freigegebenen vollständigen Source-Unlink/Purge darf nicht verändert oder indirekt aktiviert werden.
- Keine vollautomatische Weiterleitung persönlicher Posteingänge; Nutzer verschieben gezielt archivierungswürdige Nachrichten.
- Getrennte Entwicklungs-/Produktivfreigaben für (a) Dovecot-Freigaben und (b) Paperless-Dokument-ACL. Keine Freigabe allein aufgrund erfolgreicher Dovecot-Konfigurationssyntax.

## Zielpostfach und IMAP-Ablage

Geplante technische Mailbox: `paperless@thebergens.net` (nur verwenden, wenn die Domain aktiv bedient wird und die LDAP-Identität `paperless` in der tatsächlichen Empfänger-/`Mailuser`-Konfiguration freigegeben ist).

Auf diesem Konto:

```text
Privat/
  thomas/{Eingang,Verarbeitet,Fehler}
  nadja/{Eingang,Verarbeitet,Fehler}
  nils/{Eingang,Verarbeitet,Fehler}
  linda/{Eingang,Verarbeitet,Fehler}
Eltern/{Eingang,Verarbeitet,Fehler}
Familie/{Eingang,Verarbeitet,Fehler}
```

Ordnernamen in Dovecot/IMAP mit `/` als Hierarchietrenner; in den persönlichen Clients via gesichertem Freigabe-Namespace (z. B. `Shared/paperless/...`) sichtbar. Reale Namespace-Darstellung vor dem Rollout mit mindestens Apple Mail und einem weiteren IMAP-Client prüfen. Das Mailbox-`INBOX` des technischen Kontos wird **nicht** als Quelle importiert, da eingehende Mails sonst nicht eindeutig einem Berechtigungsbereich zugeordnet wären.

### Zugriffsmatrix

| Konto | Privat/thomas | Privat/nadja | Privat/nils | Privat/linda | Eltern | Familie |
| --- | --- | --- | --- | --- | --- | --- |
| thomas | Eingang einlegen, Status lesen | kein automatisches Recht | separat nach Sorgerechtsfreigabe | separat nach Sorgerechtsfreigabe | Eingang einlegen, Status lesen | Eingang einlegen, Status lesen |
| nadja | kein automatisches Recht | Eingang einlegen, Status lesen | separat nach Sorgerechtsfreigabe | separat nach Sorgerechtsfreigabe | Eingang einlegen, Status lesen | Eingang einlegen, Status lesen |
| nils | – | – | Eingang einlegen, Status lesen | – | – | Eingang einlegen, Status lesen |
| linda | – | – | – | Eingang einlegen, Status lesen | – | Eingang einlegen, Status lesen |
| paperless (technisch) | Vollzugriff | Vollzugriff | Vollzugriff | Vollzugriff | Vollzugriff | Vollzugriff |

Private Erwachsenendokumente werden **nicht** automatisch gegenseitig freigegeben. Für die privaten Kinderbereiche sind etwaige Elternrechte gesondert und nachgewiesen zu konfigurieren – keine implizite Freigabe durch die LDAP-Gruppe `Familie`.

Für Dovecot 2.4 `shared`-Namespace und `acl`/`imap_acl` mit ACL-Backend `vfile` und `acl_sharing_map` verwenden; keine unsicheren Symlinks oder allgemeinen `anyone`-ACLs. Zugriffsrechte pro freigegebenem Blatt: für `Eingang` nur `lookup`, `read`, `insert`; für `Verarbeitet` und `Fehler` nur `lookup`, `read`; notwendige `lookup`-Rechte auf übergeordneten Ordnern. `delete`, `expunge`, `create`, `admin` nicht an die einliefernden Nutzer delegieren. Hinweis: Mit `insert` darf Mail in den Ordner kopiert/verschoben werden, aber zum Entfernen aus dem **eigenen Quellordner** muss der Benutzer dort selbst Löschrechte besitzen.

Die technische Mailbox authentifiziert ausschließlich sich selbst; Paperless benötigt **keine** Zugangsdaten der persönlichen Benutzerpostfächer. SMTP-Sendeberechtigung der technischen Identität separat sperren, sofern keine technische Notwendigkeit besteht; das bisherige LDAP-`passdb`-Modell erlaubt sonst Submission grundsätzlich auch für technische Konten.

## Paperless-ngx: sechs E-Mail-Regeln + Berechtigungs-Workflows

In `Paperless → Verwaltung/E-Mail` ein IMAP-Konto für den technischen Benutzer einrichten. Ausschließlich die sechs `.../Eingang`-Ordner abrufen. Je Regel bei erfolgreich entnommenem Anhang die Mail nach `.../Verarbeitet` bewegen; keine Löschung und kein `Mark as read` als Ersatz für kontrollierte Verschiebung. Vor dem ersten Liveabruf alle sechs Workflows gegen produktive Dokument-ACL prüfen.

| Mailregel | Paperless-Bereich | Eigentümer / Ansicht / Bearbeitung |
| --- | --- | --- |
| `Privat/thomas/Eingang` | privat thomas | Eigentümer thomas, keine zusätzliche Familienfreigabe |
| `Privat/nadja/Eingang` | privat nadja | Eigentümer nadja, keine zusätzliche Familienfreigabe |
| `Privat/nils/Eingang` | privat nils | Eigentümer nils; elterliche Sonderrechte nach separatem Test |
| `Privat/linda/Eingang` | privat linda | Eigentümer linda; elterliche Sonderrechte nach separatem Test |
| `Eltern/Eingang` | Eltern | Eigentümer nach definiertem Dokumentmodell, Gruppe Eltern: Ansicht und Bearbeitung |
| `Familie/Eingang` | Familie | Eigentümer nach definiertem Dokumentmodell; Gruppe Familie: Ansicht; Eltern: Bearbeitung |

Workflows auf `Consumption Started` mit **Filter auf die spezifische Mailregel** anlegen, nicht nur nach Tag oder Absender. Standarddokumente aus Mailabruf erhalten nicht automatisch durch Ordnernamen ein korrektes Objekt-ACL. Fehlendes/ambiges Eigentümer- oder Gruppenziel muss den Produktivabruf blockieren.

Paperless kann den Originalanhang aufnehmen und eine Mail danach verschieben; laut Dokumentation kann der eigentliche Dokumentverarbeitungsprozess danach noch scheitern. `Verarbeitet` bedeutet daher nur „vom Mail-Consumer angenommen“, **nicht** automatisch „Dokument abschließend OCR-verarbeitet und berechtigt archiviert“. Für einen belastbaren Ende-zu-Ende-Nachweis sind Dokument-ID, Eigentümer, ACL, Verarbeitungsstatus und IMAP-Metadaten getrennt zu prüfen. `Fehler` dient zunächst als manuelle Nachbearbeitung; Paperless verschiebt fehlgeschlagene Verarbeitungen nicht automatisch verlässlich dorthin.

## Epson ET-4750 und adressgesteuerter Scaneingang

**Entscheidung:** Zwei Empfängeradressen für die gemeinsamen Scanbereiche, ohne Betreffkonvention:

| Ziel im Epson / anderer Mailclient | Empfängeradresse (geplant, noch nicht produktiv) | Zustellung auf `paperless` |
| --- | --- | --- |
| Paperless Familie | `scan-familie@thebergens.net` | `Familie/Eingang` |
| Paperless Eltern | `scan-eltern@thebergens.net` | `Eltern/Eingang` |

Der Standardbetreff `Scan vom Drucker` kann bleiben. Betreff/Dateiname sind Metadaten, keine Berechtigungssteuerung. Die gleiche Empfängeradresse funktioniert auch beim manuellen Senden von Dokumenten über ein Mailprogramm. Die Mail-Domain muss in der tatsächlichen produktiven Mailkonfiguration existieren.

### Epson-Gerätegrenze und Datenschutz

Der vorhandene **Epson EcoTank ET-4750** bietet am Bedienfeld `Scan → Cloud` und versendet E-Mail-Scans **über Epson Connect**; dies ist keine direkte lokale SMTP-Anmeldung des Druckers am `bergen-mail`-Backend. Die beiden Ziele müssen gegebenenfalls in der Epson-Connect-Zielliste konfiguriert werden. Je Ziel ist ein eigener Anzeigename möglich. Epson erhält bei diesem Transportweg die Scandaten. Daher insbesondere für vertrauliche Eltern-Dokumente **den bereits vorhandenen lokalen Synology-Scannerpfad beibehalten und bevorzugen**. Die neuen E-Mail-Adressen sind eine ergänzende Eingangsmöglichkeit, kein Ersatz für den geschützten NAS-Scanworkflow.

Referenzen:
- https://epson.com/faq/SPT_C11CG19201~faq-0000603-et4750?faq_cat=faq-8796127569996
- https://www.epsonconnect.com/guide/de/html/uses_2.htm
- https://www.epsonconnect.com/help/de/html/scan_1.htm

### Mailrouting: Ziel-E-Mailadresse → vorhandener Eingangsordner

Nur **eingehend** definierte Aliase `scan-familie` und `scan-eltern` → `paperless+familie` bzw. `paperless+eltern`; Postfix und Dovecot LMTP müssen Detailadressen per `recipient_delimiter = +` erhalten, und Dovecot Sieve/Pigeonhole darf **nur die beiden explizit erlaubten Details** auf `Familie/Eingang` bzw. `Eltern/Eingang` per `fileinto` abbilden. Kein automatisches `fileinto :create`, kein offenes Wildcard-Subaddress-Mapping und kein Vertrauen in die sichtbare `To:`-Kopfzeile. Die effektive Envelope-Adresse muss durch SMTP- und LMTP-End-to-End-Tests nachgewiesen werden: Aliase und Postfix-Umschreibung können ansonsten den Detailteil verlieren. Alternativ, falls Detailadressen in dieser Installation nicht stabil beibehalten werden, zwei getrennte technische Empfangspostfächer anlegen und diese durch Paperless als gesonderte IMAP-Konten abonnieren; nicht auf Betrefftrennung zurückfallen.

Für diese **empfangsseitigen** Scan-Aliase keine pauschale `send_as`-Erlaubnis vergeben. Die bestehende Mail-Backend-Rolle verlangt derzeit `send_as` für **jeden** Alias: Erweiterung für ausdrücklich `receive_only` deklarierte Aliase mit negativer SMTP-Submission-Prüfung erforderlich. Den bestehenden Sender-Autorisierungsvertrag nicht durch Dummy-Berechtigungen umgehen.

### Mailsecurity und Annahmebedingungen

- Ein öffentlicher Zielalias ist keine Authentifizierung. Der reine Empfängername darf nicht als Nachweis gelten, wer die Mail eingeworfen hat, und ist deshalb kein alleiniger Vertrauensanker für die automatische Archivierung in einem geschützten Bereich.
- Der öffentliche MX2/Gateway prüft SPF/DKIM/DMARC und Rspamd; anwendungsspezifische Sender-Allowlist (nach verifizierter realer Epson-Connect-Sendeidentität und zusätzlich genau benannten Familienabsendern) bzw. separates Quarantäne-/Freigabeverfahren planen. Identische sichtbare From-Adressen von beliebigen Absendern nicht ungeprüft zulassen.
- PDF-Anhänge begrenzen, unterstützte MIME-/Dateitypen testen, kein sofortiges Löschen der Quellmail. Doppelte Nachrichten, fehlende Anhänge und Fehlzuordnung sind Negativtests.
- Paperless-Workflows werden **auf die tatsächlich konsumierende Mailregel** gefiltert, nicht auf Betreff oder ungeprüfte Absenderadresse. `Eltern` darf für Kinder keine Liste-, Lese-, Einlege- oder Dokumentrechte eröffnen.

### Abnahme des Drucker-/Mail-Eingangs

1. Epson-Cloud-Zielliste als optionalen, explizit cloudbasierten Versandweg kennzeichnen. Bestehenden lokalen NAS-Scanweg unverändert erhalten.
2. Auf `bergen-mail`: `postmap -q`, lokaler SMTP-RCPT-Test (je Alias), Postfix-Queue / LMTP Logs und `doveadm mailbox list` auf korrekte Ordnerzustellung prüfen.
3. Je Ziel einen Test-PDF-Anhang versenden; Betreff darf `Scan vom Drucker` sein, muss aber für die Trennung unerheblich sein.
4. Nach gesichertem Paperless-Import die Dokument-Owner/ACL für Eltern/Familie und die Verschiebung nach `Verarbeitet` prüfen.
5. Unbekannte Empfänger, falsche Absender, Anhang-lose Mails und Kinderzugriff auf Eltern gezielt negativ testen.
6. Nur nach dokumentierter Abnahme die Aliase und Mailregeln produktiv freigeben.

Dovecot-Referenzen:
- https://doc.dovecot.org/2.4.5/core/config/delivery/lmtp.html
- https://doc.dovecot.org/2.4.5/core/plugins/sieve.html
- https://doc.dovecot.org/2.4.2/howto/sieve.html

## Reproduzierbare Implementierungsschritte (noch nicht ausgeführt)

1. Produktiven Dovecot-LXC und tatsächlich bediente Domains/LDAP-Mitgliedschaften read-only prüfen, vollständiges Mail-Backup inklusive `/var/vmail` und ein getrenntes Wiederherstellungsszenario nachweisen.
2. Technische LDAP-`Mailuser`-Identität `paperless` standortbezogen erstellen, IMAP-Authentifizierung von Paperless-Netz erreichbar machen, SMTP-Submission technisch minimieren.
3. Dovecot-Shared-Namespace samt ACL-Plugin **opt-in** in die Mail-Backend-Ansible-Rolle aufnehmen, `doveconf`/Rollback prüfen, bestehende IMAP-Clients nicht beeinträchtigen.
4. Ordner und exakt deklarierte ACLs create-only und idempotent provisionieren, `doveadm acl recalc` ausführen; niemals fremde ACLs stillschweigend erweitern oder Maildaten löschen.
5. Zugriffstest mit allen vier Konten und Paperless: positives Einlegen, negatives LIST/SELECT/COPY auf verbotene Ordner (besonders Kinder → Eltern und Geschwister → Privat).
6. Eine isolierte Testnachricht pro Bereich; Paperless-Mailregel und Workflow zunächst deaktiviert anlegen, Berechtigungsmatrix und Cross-User-Negativtests durchführen.
7. Erst danach sechs Mailregeln freischalten. Verarbeitungs-/Fehlerfälle, doppelte Anhänge, erneut zugestellte Nachrichten, Neustarts und fehlgeschlagene OCR/ACL-Zuweisungen prüfen.
8. Mail-Retention, Backup und Restore von Quelle sowie `Verarbeitet` festlegen. **Keine** automatische Mail- oder PDF-Löschung im ersten Release.

## Offene Nachweise vor Livefreigabe

- Aktuelle produktive Mailboxquelle auf `bergen-mail` verifizieren: Das Repository dokumentiert zunächst nur die installierte Basis und einen noch offenen Cutover; eine laufende Postfix-/Dovecot-Instanz allein belegt keine endgültige produktive Mailmigration.
- Site-spezifische Domains, genaue IMAP-Namensräume, Proxmox-Firewall und LDAP-Filter aus ignorierter `bergen-mail.yml` statt aus der Beispielkonfiguration entnehmen.
- Bereits bestehende produktive Paperless-Workflow-/OIDC-/Gruppen-ACL nicht überschreiben. Für Untergruppen privat/Eltern/Familie positive **und negative** Zugriffstests dokumentieren.
- Paperless-Versionsstand aus dem aktiven Container und nicht nur aus älteren Installationsnotizen ermitteln.

## Externe Referenz

- https://doc.dovecot.org/2.4.4/core/config/shared_mailboxes.html
- https://doc.dovecot.org/2.4.4/core/plugins/acl.html
- https://docs.paperless-ngx.com/usage/#incoming-mail
- https://docs.paperless-ngx.com/usage/#workflows
