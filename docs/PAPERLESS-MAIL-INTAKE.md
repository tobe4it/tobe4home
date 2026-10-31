# Paperless-Mailablage auf bergen-mail – Entwurf / kein Produktiv-Cutover

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

Direkte Zustelladressen `paperless-eltern@...` und `paperless-familie@...` wären eine spätere Erweiterung. Reine Postfix-Aliase auf das gemeinsame Konto würden beide Empfänger im selben `INBOX` mischen. Erst mit separat getesteter Sieve-/Envelope-Empfänger-Zuordnung auf die korrekten Eingangsordner aktivieren.

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
