# Sicherer Umstieg auf einen Chat-first-Bootstrap

**Status: Vorbereitung, NICHT zur Löschung freigegeben.**
Diese Anleitung ist die verbindliche Gate-Reihenfolge für die Ablösung des
existierenden tobe4home-Testcontrollers CT1001. Keine Proxmox-Löschoperation
darf durch eine Git-Änderung oder CI automatisch ausgelöst werden.

## Aktueller belegter Stand

- `bootstrap/launch.sh` ist der derzeitige einzige aktive Installer-Einstieg.
  Er führt zu `bootstrap/single-controller.sh`.
- Dieser Installer erzeugt einen unprivilegierten Rocky-Linux-10-Controller
  und installiert **AnsibleForms 7.4.2 und RTE**, aber **noch keine tobe4home-
  Chatoberfläche und keinen LLM-Endpunkt**.
- Der Anwender hat die hostseitige Proxmox-Bestandsaufnahme und ihren Transfer
  in den RTE erfolgreich getestet (`ok=6, changed=0, failed=0`).
- `bootstrap/deploy-service-planner-1001.sh` installiert nur ein
  **nicht ausführendes Vorschauformular**, keinen Chat.
- Kein Freigabe-Executor, keine Proxmox-Schreibrechte und keine automatisierte
  Bereitstellung weiterer LXCs/VMs vorhanden.
- **Ergebnis:** Ein sofortiger Reset mit anschließendem `launch.sh --apply`
  würde eine funktionierende AnsibleForms-Referenz durch eine ähnlich
  eingeschränkte AnsibleForms-Installation ersetzen. Das ist kein sinnvoller
  Produktfortschritt.

## Unterstützter vs. historischer Bootstrap

| Pfad | Klassifizierung |
| --- | --- |
| `bootstrap/launch.sh` → `single-controller.sh` | Aktiver *experimenteller* AnsibleForms-Bootstrap |
| `bootstrap/reset-controller.sh` | Separates, destruktives Wartungswerkzeug **nur für den geprüften CT1001**, kein Bootstrap |
| `bootstrap/deploy-onboarding-1001.sh` | Kontrollierte Nachrüstung auf CT1001 |
| `bootstrap/deploy-service-planner-1001.sh` | Kontrollierte Vorschau-Nachrüstung ohne LLM/Deployment |
| `bootstrap/bootstrap.sh`, `installer-tui.sh`, `wizard.py`, `deploy-ansible-controller.sh`, `resume-ansible-controller.sh`, `import_stage0_site.py` | **Historische Stage-0-/Stage-1-Werkzeuge, nicht mehr zum Betrieb verwenden** |

Historische Werkzeuge vorerst weder blind löschen noch beim Neuaufbau
aufrufen: Tests, importierende Module und Migrations-/Recovery-Pfade müssen
zuerst separat geprüft und auf einen `legacy/`-Bereich umgestellt oder
aus dem aktiven Paket ausgeschlossen werden.

## Gate A – neues Bootstrap-Artefakt funktionsfähig

Vor irgendeinem Löschen müssen im neuen Entwicklungszweig mindestens
folgende Eigenschaften implementiert und getestet sein:

- [ ] Genau ein CT1001, Rocky Linux 10, unprivilegiert, keine CT1000-Kette;
      begrenzte Host-Preflight-Prüfungen, klare manuelle `INSTALL 1001`
      Freigabe und reproduzierbare Fehlerwiederaufnahme.
- [ ] Der Controller stellt eine **eigene, authentifizierte tobe4home-
      Chatoberfläche** als Standardstartseite bereit, ohne den Benutzer
      zuerst in AnsibleForms-Demoformulare zu leiten.
- [ ] Verbindung zu einem autorisierten LLM-Endpunkt, mit sicherem
      Fallback bei nicht konfiguriertem Modell.
- [ ] Ein Prompt wie „Richte einen DNS-Filter ein“ wird in ein strukturiertes
      **nicht ausführendes** Dienstkonzept überführt, das Nutzerabsicht,
      fehlende Angaben und Auswirkungen verständlich zeigt.
- [ ] Verbindliche Trennung: Chat/Modell keine Hypervisor-Credentials,
      kein generierter Shellcode auf dem PVE-Host, keine unautorisierte
      Ansible-/OpenTofu-Ausführung.
- [ ] Vorhandene Proxmox-LXC/VMs bleiben bei Discovery und Testläufen
      unverändert. Keine automatische Übernahme von Altgasten.
- [ ] Installation, Anmeldung, Chat und negative Security-Tests laufen
      reproduzierbar in einer **isolierten Testumgebung**, ohne
      produktive CT1001 zu zerstören.

**Erst nach Gate A kann ein neuer Chat-first-Bootstrap auf venombox sinnvoll
abgenommen werden.** Proxmox-Schreibberechtigungen und vollständiges
Dienst-Deployment bleiben ein separates Gate B (ADR-002 / Issue #3).

## Gate B – sichern, kontrolliert zurücksetzen, neu starten

Nur wenn Gate A bestanden ist und der Betreiber ausdrücklich den Ersatz von
CT1001 möchte:

1. Aktuelle CT1001-Konfiguration und Zugehörigkeit **lesend** prüfen.
   Bei zusätzlichem Mount, Snapshot, abweichendem RootFS oder Identität:
   automatisierten Reset **nicht** fortsetzen.
2. **Vollständiges externes Backup** des CT und notwendiger
   standortspezifischer Daten/Schlüssel, ausschließlich an einen
   verifizierten, vom CT unabhängigen Speicherort. Speicherort,
   Lesbarkeit, Prüfsumme und eine nachweislich mögliche Wiederherstellung
   prüfen. Ein ungetestetes lokales Volume ersetzt diese Kontrolle nicht.
3. Der vorhandene Reset bleibt **ein eigenes, manuell freizugebendes
   Kommando**. Zuerst nur Vorschau:

   ```bash
   sudo bash /root/tobe4home-bootstrap/bootstrap/reset-controller.sh
   ```

4. Nur nach gesonderter Prüfung der Ausgabe und ausdrücklicher Entscheidung
   des Operators:

   ```bash
   sudo bash /root/tobe4home-bootstrap/bootstrap/reset-controller.sh --destroy
   # verlangt exakt DELETE 1001
   ```

   Der Reset darf ausschließlich den eindeutig identifizierten
   `tb4h-controller` und seinen Proxmox-verwalteten RootFS betreffen.
   **Keine** `rm -rf /var/lib/lxc/1001`, keine `pct destroy --force`,
   keine `--destroy-unreferenced-disks`, keine beliebigen Fremdgäste
   oder Backups. Wenn der Reset ablehnt: stoppen, nicht umgehen.
5. Erst anschließend die **nach Gate A freigegebene neue Version** von
   `bootstrap/launch.sh` zunächst als Read-only-Vorschau aufrufen und
   Ressourcen/Netz, Storage, DNS, Schlüssel, Gast-VMID und Plan prüfen.
   Der bisherige AnsibleForms-only-Stand darf **nicht** als Chat-first
   neu installiert werden.
6. Die neue Instanz zunächst ohne Proxmox-Schreibrechte abnehmen:
   Chat-Login, LLM-Endpunkt, Prompt→Plan, unveränderte Nachbargäste,
   Backup/Restore, Audit. Danach das separate Provisioning-Gate.

## Sicherheitsregel

**Kein Cleanup-Commit löscht Hostdaten. Kein Reset vor nachweislich
funktionierendem Ersatz. Kein neues Bootstrap mit falschem Produktversprechen.**

Verbindliche Architektur: [ADR-003](ADR-003-LLM-CHAT-FIRST-PLATFORM.md);
Proxmox-Execution: [ADR-002](ADR-002-CONTROLLER-PROXMOX-PROVISIONING.md).
