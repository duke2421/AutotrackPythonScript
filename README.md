# AutotrackPythonScript
Based on the Autotrack SCript from Polyfjord https://gist.github.com/polyfjord/fc22f22770cd4dd365bb90db67a4f2dc

## Verwendung unter Windows

Dieses Script automatisiert die Installation und Abwicklung von Tracking-Tools.

1. Python 3 mit Tkinter installieren.
2. Repository herunterladen und entpacken.
3. Script mit `python AutoTracker_GUI-v4.py` starten.
4. In der GUI über **Install tools** und **Test tools** den üblichen Workflow durchlaufen.

## Verwendung unter Linux

Unter Linux dient das Script ebenfalls der automatisierten Installation und Nutzung der Tracking-Tools. Es kann alle benötigten Abhängigkeiten und Tools eigenständig herunterladen, installieren und kompilieren. Beim Start prüft es, ob Tkinter vorhanden ist, und bietet eine automatische Installation an; alternativ muss Tkinter vor dem Start manuell installiert werden.

1. Python 3 bereitstellen.
2. Repository klonen oder entpacken.
3. Script mit `python3 AutoTracker_GUI-v4.py` starten.
4. In der GUI die gewünschten Installations- und Testschritte ausführen.

*Das Kompilieren von COLMAP und GLOMAP wurde nur unter Linux Mint getestet und kann auf anderen Distributionen fehlschlagen.*
