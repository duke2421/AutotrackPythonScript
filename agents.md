# agents.md — Arbeitsanweisung für Codex (AutoTracker_GUI)

**Zweck**
Diese `agents.md` beschreibt, wie ein automatisierter Entwicklungs‑Agent (z. B. "codex") das Projekt **AutoTracker_GUI** weiterentwickelt. Ziel ist: konsistente, nachvollziehbare, sichere Änderungen mit möglichst **minimalen Diffs** und vollständigen, lauffähigen Script‑Files als Ergebnis.

> Bezug: Das zu entwickelnde Script ist `AutoTracker_GUI-v4.py` (als Basis). Bitte bei allen Änderungen darauf Bezug nehmen. fileciteturn0file0

---

## Grundregeln (nicht verhandelbar)
1. **Immer das komplette Script zurückliefern** — niemals nur Code‑Häppchen. Der Nutzer verlangt komplette Dateien als Download / Patch.
2. **Nur tatsächlich nötige Änderungen** durchführen. Keine kosmetischen Änderungen (Leerzeilen, Einrückungen, Kommentar‑Umformungen) wenn nicht zwingend.
3. **Windows‑Logik darf nicht verändert werden.** Änderungen dürfen Windows‑Spezifika nur lesen/testen, nicht umbauen (außer nach expliziter Erlaubnis).
4. **Linux‑Änderungen sind erlaubt**, aber müssen Windows‑Kompatibilität nicht brechen.
5. **Keine automatische Auto‑Formatting‑Tools** (Black, yapf, etc.) ausführen, wenn dadurch unnötige Diffs entstehen. Falls ein Formatter benutzt wird, dokumentiere jede Änderung explizit im PR.
6. **Teste lokal bevor Commit:** mind. Starten der GUI auf dem Ziel‑OS und Ausführen der Installer‑Dialog‑Routine (sofern betroffen).

---

## Git / Workflow
1. **Vor jedem Arbeitsbeginn**: Hol die aktuellste `main`:

```bash
git fetch origin
git checkout main
git pull --ff-only origin main
```


2. **Commit‑Regeln**
   - Commit‑Message (prägnant):
     `feat: <Kurzbeschreibung> (AutoTracker_GUI-v2.dev_008.py)`
   - Body (bei Bedarf): kurze, technische Erklärung und warum die Änderung minimal ist.

3. **Pull Request / Merge**
   - PR‑Titel: `AutoTracker: <Kurzbeschreibung> — dev_008`
   - PR‑Beschreibung: Liste der geänderten Stellen (Datei + Funktion + Zeilennummern), kurze QA‑Anleitung, was getestet wurde (OS, Befehle, erwartetes Verhalten), und Hinweis, dass **Windows‑Logik nicht verändert** wurde.

---

## Entwicklungs‑ und Testanweisungen
### Lokales Setup (schnell)
- Python: **3.10+** (mögliche Abweichung vom Zielsystem beachten)
- Benötigte Module: `tkinter` (Systemabhängig), `git`, `cmake`, `ninja`, `ffmpeg` (optional), `colmap`/`glomap` (nur für Integrationstests)

**Linux (Debian/Ubuntu) Beispiel:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-tk git cmake ninja-build ffmpeg
```

**Windows:**
- Python3: Installation mit entsprechenden Tcl/Tk‑Komponenten (Tkinter aktiviert).
- Für Tests: Vorhandene COLMAP/GLOMAP/FFmpeg‑Binärpfade prüfen.

### Schnelltest (nach Änderung)
1. Starte das Script vollständig: `python3 AutoTracker_GUI-v2.dev_008.py`
2. GUI öffnet sich → **keine** Tracebacks beim Starten.
3. Öffne `Info`‑Dialog: Buttons (PayPal/Patreon) müssen arbeiten (öffnen Browser).
4. Öffne `Install tools` Dialog und simuliere einen Install‑Durchlauf (nur Lesen/Loggen). Falls Netzwerk/Downloads nötig, mocken oder prüfen, dass Ablauf keine ungewollten Systemänderungen verursacht.
5. Teste `Test tools` Button — überprüfe, dass `ffmpeg`, `colmap`, `glomap` Aufrufe korrekt gemeldet werden (falls Pfade vorhanden).
6. Falls Änderungen die Installer‑Logik betreffen: Teste auf Linux (ein Paket‑Installationsdurchlauf) und Windows (Zip‑Extraktion Pfadkopien). Achte auf `_batched_pkg_install` Flag‑Logik (ein Passwort‑Prompt auf Linux ist erwünscht — aber nur einmal).

---

## Stil‑ und Qualitätsanforderungen
- **Selbst dokumentieren:** Jede nicht‑triviale Änderung muss inline kommentiert werden (kurz, präzise).
- **Keine Redesigns** der GUI ohne Rückfrage.
- **Konservatives Refactoring:** Wenn Refactoring nötig, splitte in kleine Schritte und liefere Tests / manuelle QA‑Anleitung.
- **Fehlerbehandlung:** Logausgaben verwenden (`self._log_install` / `log_line`) statt stummer `print()` Aufrufe.

---

## Spezielle Hinweise für bekannte Bereiche (aus `AutoTracker_GUI-v4.py`)
- **Installer:** Stapel‑Installation unter Linux: Sammle Pakete und rufe `pkg_install(pm, all_pkgs, log_fn)` einmal auf — vermeide mehrere Paketmanager‑Aufrufe. Der Agent sollte die Variable `_batched_pkg_install` richtig setzen/prüfen.
- **Windows extractor/copy:** Verwende `_win_copy_tool_bin` / `_copytree_overwrite` und verändere Pfad‑/DLL‑Logik nur wenn nötig. Insbesondere: ANGLE DLL Ergänzung (`_win_ensure_angle_dlls`) und VC++‑Redist‑Prüfung nicht entfernen.
- **Dateinamens‑ und Versionskonventionen:** siehe oben.

---

## PR‑Checklist vor Merge (Abhakliste)
- [ ] `main` vor Start frisch gezogen.
- [ ] Branch mit aussagekräftigem Namen erstellt.
- [ ] Dateiname für dev‑Release korrekt (`AutoTracker_GUI-v2.dev_008.py`).
- [ ] Nur notwendige Zeilen geändert — keine unnötigen Whitespaces/Kommentare.
- [ ] Script lokal gestartet (Linux + Windows, falls möglich) — Start ohne Tracebacks.
- [ ] Installer/`test_tools` falls betroffen getestet und Logausgaben geprüft.
- [ ] PR‑Beschreibung enthält Testanweisungen und möglichen Rollback‑Plan.

---

## Umgang mit Rückfragen / Unsicherheiten
Wenn unklar, wie sich eine Änderung auf Windows auswirkt — **erst** eine minimale, lokalisierte Änderung commiten und im PR deutlich kennzeichnen. Wenn Risk/Unsicherheit hoch, lege stattdessen einen Vorschlags‑Patch mit `# TODO`/`# REVIEW` Kommentaren vor.

---

## Beispiele
**Commit‑Message:**
```
fix(installer): collect packages in single batch to avoid multiple password prompts (AutoTracker_GUI-v2.dev_008.py)
```

**PR‑Beschreibung (Kurz):**
```
Änderung: Linux package collection now runs in a single batched pkg_install call to avoid multiple sudo prompts.
Files: AutoTracker_GUI-v2.dev_008.py
QA: Start script on Ubuntu 24.04, open installer, check log for single pkg_install command. Windows unaffected.
```

---

## Zusatz: Automatisierte Schritte (optional)
- Optional kann der Agent ein kleines `precheck.sh` / `precheck.ps1` erzeugen, das lokal prüft, ob `tkinter`, `ffmpeg`, `cmake`, `git` vorhanden sind.
- **WICHTIG:** Solche Hilfs‑Skripte dürfen das System nicht verändern (kein `sudo` ohne ausdrückliche Erlaubnis). Sie sollten nur Prüfungen durchführen.

---

Wenn Du möchtest, kann ich diese `agents.md` in eine Datei im Repo schreiben (als `agents.md`) und zusätzlich ein Beispiel‑`precheck.sh` erzeugen.  

---

*Ende agents.md*
