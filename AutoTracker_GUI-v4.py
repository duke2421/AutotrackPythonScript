#!/usr/bin/env python3

import json
import locale
import os
import platform
import shlex
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"
DEFAULT_SETTINGS = {"ask_create_structure": True, "top_dir": ""}

def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {**DEFAULT_SETTINGS, **data}
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()

def save_settings(cfg):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# --- Windows ANGLE-DLL Sicherung ---
# Ergänzt libEGL/libGLESv2/opengl32sw/d3dcompiler_47 wenn im colmap/bin fehlen.
def _win_ensure_angle_dlls(colmap_dir: Path, sources_dir: Path, log):
    """Ensure libEGL/libGLESv2/opengl32sw/d3dcompiler_47 are present in colmap\bin.
    Try to extract them from official COLMAP zips (nocuda/cuda) if missing.
    """
    try:
        if os.name != 'nt':
            return
        bin_dir = colmap_dir / 'bin'
        needed = ['libEGL.dll', 'libGLESv2.dll', 'opengl32sw.dll', 'd3dcompiler_47.dll']
        missing = [n for n in needed if not (bin_dir / n).exists()]
        if not missing:
            log('[INSTALL] ANGLE/Software-OpenGL DLLs vorhanden.')
            return
        log(f"[INSTALL] ANGLE-DLLs fehlen: {', '.join(missing)} -> versuche aus COLMAP-ZIPs zu ergänzen…")
        zips = [
            ('colmap-x64-windows-nocuda.zip', 'https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-nocuda.zip'),
            ('colmap-x64-windows-cuda.zip',   'https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-cuda.zip'),
        ]
        from zipfile import ZipFile
        for fn, url in zips:
            zpath = sources_dir / fn
            if not zpath.exists():
                try:
                    download_file(url, zpath, log)
                except Exception as e:
                    log(f"[INSTALL] Hinweis: Konnte {fn} nicht laden: {e}")
                    continue
            try:
                with ZipFile(zpath) as zf:
                    members = {n: None for n in needed}
                    for zi in zf.infolist():
                        lower = zi.filename.lower()
                        for dll in needed:
                            if lower.endswith('/bin/' + dll.lower()):
                                members[dll] = zi
                    any_extracted = False
                    for dll, zi in members.items():
                        if zi is None: continue
                        target = bin_dir / dll
                        bin_dir.mkdir(parents=True, exist_ok=True)
                        with zf.open(zi) as src, open(target, 'wb') as dst:
                            dst.write(src.read())
                        any_extracted = True
                    if any_extracted:
                        still_missing = [n for n in needed if not (bin_dir / n).exists()]
                        if not still_missing:
                            log('[INSTALL] ANGLE-DLLs ergänzt (aus COLMAP-Zip).')
                            return
                        else:
                            log(f"[INSTALL] Noch fehlend: {', '.join(still_missing)} (nächster Versuch)…")
            except Exception as e:
                log(f"[INSTALL] Fehler beim Entpacken {zpath.name}: {e}")
        log('[INSTALL] Warnung: ANGLE-DLLs konnten nicht automatisch ergänzt werden.')
    except Exception as e:
        log(f"[INSTALL] Warnung: ANGLE-DLL-Check fehlgeschlagen: {e}")


# --- VC++ Redistributable Check ---
# Prüft vcruntime DLLs in System32/SysWOW64.
def _win_has_vc_redist() -> bool:
    try:
        if os.name != 'nt':
            return True
        sysroot = os.environ.get('SystemRoot', r'C:\\Windows')
        cand = [
            Path(sysroot) / 'System32' / 'vcruntime140.dll',
            Path(sysroot) / 'System32' / 'vcruntime140_1.dll',
            Path(sysroot) / 'SysWOW64' / 'vcruntime140.dll',
            Path(sysroot) / 'SysWOW64' / 'vcruntime140_1.dll',
        ]
        return any(p.exists() for p in cand)
    except Exception:
        return False

def _win_ensure_vc_redist(sources_dir: Path, log):
    try:
        if not _win_has_vc_redist():
            log("[INSTALL] VC++ Redistributable fehlt -> lade und installiere…")
            vc_url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            from urllib.parse import urlsplit
            vc_exe = sources_dir / Path(urlsplit(vc_url).path).name
            download_file(vc_url, vc_exe, log)
            cmd = [str(vc_exe), "/install", "/quiet", "/norestart"]
            try:
                subprocess.run(" ".join(f'\"{c}\"' for c in cmd), shell=True, check=False)
            except Exception as e:
                log(f"[INSTALL] Warnung: VC++ Installer konnte nicht gestartet werden: {e}")
            if _win_has_vc_redist():
                log("[INSTALL] VC++ Redistributable installiert.")
            else:
                log("[INSTALL] Warnung: VC++ Redistributable scheint noch zu fehlen.")
        else:
            log("[INSTALL] VC++ Redistributable bereits vorhanden.")
    except Exception as e:
        log(f"[INSTALL] Warnung: VC++ Prüfung/Installation fehlgeschlagen: {e}")

def ensure_vc_redist():
    if os.name != "nt" or _win_has_vc_redist():
        return
    import tkinter as tk
    from tkinter import messagebox
    lang = detect_lang(); S = I18N.get(lang, I18N["en"])
    root = tk.Tk(); root.withdraw()
    if messagebox.askyesno(S["dlg_vcredist_title"], S["dlg_vcredist_msg"]):
        _win_ensure_vc_redist(Path.cwd(), lambda msg: None)
    else:
        messagebox.showinfo(S["dlg_vcredist_title"], S["dlg_vcredist_info"])
        sys.exit()
    root.destroy()

# -*- coding: utf-8 -*-
"""
AutoTracker GUI (Python) – Cross-Platform (preferred layout)
+ i18n (DE/EN auto + dropdown)
+ Linux installer/compilers from release archives (COLMAP 3.12.3 / GLOMAP 1.1.0)
+ Project-structure creation prompt, PATH fallback search, runtime timer, FPS options

This file is based on your working version (AutoTracker_GUI_crossplat(12).py)
and merges back the language switch and all installer/compile improvements
without removing any of the controls you liked.
"""

IS_WINDOWS = (os.name == "nt")
OS_NAME = platform.system()

# ------------------------- i18n -------------------------
def detect_lang():
    try:
        lang = os.environ.get("LANG") or locale.getdefaultlocale()[0] or ""
    except Exception:
        lang = ""
    lang = lang.lower()
    if lang.startswith("de"): return "de"
    return "en"

I18N = {
    "de": {
        "app_title": "AutoTracker GUI (Python) – {os}",
        "paths_tools": "Pfade & Tools",
        "project_top": "Projekt-Top-Ordner:",
        "browse": "Durchsuchen…",
        "rediscover": "Neu erkennen",
        "os_detected": "Erkanntes Betriebssystem: {os} {distro}",
        "search_path_cb": "(Linux) Systempfad durchsuchen, falls in Projektordnern nicht gefunden",
        "search_path_btn": "Systempfad durchsuchen",
        "install_tools": "Tools installieren…",
        "ffmpeg_label": "ffmpeg:",
        "colmap_label": "COLMAP:",
        "glomap_label": "GLOMAP (optional):",
        "ffmpeg_placeholder": "Bitte die ausführbare Datei für FFMPEG auswählen",
        "colmap_placeholder": "Bitte die ausführbare Datei für COLMAP auswählen",
        "glomap_placeholder": "Bitte die ausführbare Datei für GLOMAP auswählen (optional)",
        "options": "Optionen",
        "res_title": "Frame-Extraktionsauflösung:",
        "res_keep": "Original behalten",
        "res_only_w": "Nur Breite",
        "res_only_h": "Nur Höhe",
        "res_wh": "Breite × Höhe",
        "gpu_check": "GPU verwenden (falls unterstützt) – SIFT Extraction & Matching",
        "mesh_cb": "Mesh-Erzeugung aktivieren (sehr langsam, hoher Speicherbedarf)",
        "jpeg_q": "JPEG-Qualität (-qscale:v):",
        "sift_max": "SiftExtraction.max_image_size:",
        "seq_overlap": "SequentialMatching.overlap:",
        "fps_title": "Frame-Reduktion:",
        "fps_all": "Alle Frames",
        "fps_every": "Jeden",
        "fps_every_suffix": "-ten Frame (z. B. 2 = halbe Frames)",
        "videos": "Videos",
        "add_videos": "Videos hinzufügen…",
        "remove_sel": "Auswahl entfernen",
        "clear_list": "Liste leeren",
        "scenes_dir": "Scenes-Ausgabeordner:",
        "start": "Start",
        "test_tools": "Tools testen",
        "elapsed": "Laufzeit",
        "dlg_pick_dir": "Ordner auswählen",
        "dlg_pick_file": "Datei auswählen",
        "dlg_pick_videos": "Videos auswählen",
        "dlg_create_structure_title": "Projektstruktur",
        "dlg_create_structure_msg": "Es wurden nicht alle erwarteten Ordner gefunden.\n\nSollen alle benötigten Ordner jetzt erstellt werden?",
        "dlg_create_structure_where": "Wo sollen die Ordner erstellt werden?",
        "dlg_done": "Fertig",
        "dlg_structure_created": "Ordnerstruktur wurde erstellt.",
        "msg_linux_only": "Der Systempfad-Fallback ist nur unter Linux aktiv.",
        "msg_found": "Gefunden:",
        "msg_found_none": "Keine zusätzlichen Tools im Systempfad gefunden.",
        "msg_installer_linux_only": "Der Tool-Installer ist auf Linux ausgerichtet.",
        "installer_title": "Tools installieren",
        "installer_what": "Was soll installiert/gebaut werden?",
        "installer_ffmpeg": "ffmpeg (Paketmanager)",
        "installer_colmap": "COLMAP aus Quelle bauen",
        "installer_glomap": "GLOMAP aus Quelle bauen",
        "installer_source": "Quelle (Git-URL oder Release-Archiv):",
        "installer_use_cuda": "CUDA nutzen, falls verfügbar",
        "installer_try_cuda_pkg": "(Optional) CUDA Toolkit jetzt per Paketmanager versuchen zu installieren",
        "installer_start": "Installieren starten",
        "installer_close": "Schließen",
        "installer_note": "Hinweis: Projektlokale Installation nach 01 GLOMAP/<tool>.\nRelease-Archive (.tar.gz/.zip) werden automatisch nach 06 Sources/<tool> entpackt.",
        "installer_done_ok": "Installation der Tools erfolgreich abgeschlossen",
        "installer_done_fail": "Installation der Tools mit Fehlern abgeschlossen",
        "warn_running": "Ein Durchlauf ist bereits aktiv.",
        "warn_no_videos": "Bitte mindestens ein Video hinzufügen.",
        "err_ffmpeg": "Bitte die ausführbare Datei für FFMPEG auswählen.",
        "err_colmap": "Bitte die ausführbare Datei für COLMAP auswählen.",
        "run_extract": "Frames extrahieren (ffmpeg)…",
        "run_feat": "COLMAP feature_extractor…",
        "run_match": "COLMAP sequential_matcher…",
        "run_mapper": "Sparse Reconstruction (mapper)…",
        "run_undistort": "COLMAP image_undistorter…",
        "run_patchmatch": "COLMAP patch_match_stereo…",
        "run_fuse": "COLMAP stereo_fusion…",
        "run_mesher": "Mesh erzeugen (poisson_mesher)…",
        "done_all": "Alles erledigt.",
        "tools_test_begin": "### Tools testen ###",
        "tools_test_end": "### Test abgeschlossen ###",
        "lang_label": "Sprache:",
        "lang_de": "Deutsch",
        "lang_en": "English",
            "info_btn": "Info",
        "about_title": "Info",
        "about_text": "Basiert auf dem Script von ",
        "about_link": "Polyfjord",
        "about_paypal_btn": "Spendiere mir einen Kaffee via PayPal",
        "dlg_vcredist_title": "VC++ Runtime fehlt",
        "dlg_vcredist_msg": "Die Microsoft VC++ Runtime scheint zu fehlen. Jetzt installieren?",
        "dlg_vcredist_info": "Die VC++ Runtime von Microsoft muss installiert werden, damit das Script funktioniert, Script wird beendet. Nach Installation der VC++ Runtime das Script erneut ausführen.",
},
    "en": {
        "app_title": "AutoTracker GUI (Python) – {os}",
        "paths_tools": "Paths & Tools",
        "project_top": "Project top folder:",
        "browse": "Browse…",
        "rediscover": "Re-detect",
        "os_detected": "Detected OS: {os} {distro}",
        "search_path_cb": "(Linux) Search system PATH if not found in project folders",
        "search_path_btn": "Search PATH",
        "install_tools": "Install tools…",
        "ffmpeg_label": "ffmpeg:",
        "colmap_label": "COLMAP:",
        "glomap_label": "GLOMAP (optional):",
        "ffmpeg_placeholder": "Please select the executable for FFMPEG",
        "colmap_placeholder": "Please select the executable for COLMAP",
        "glomap_placeholder": "Please select the executable for GLOMAP (optional)",
        "options": "Options",
        "res_title": "Frame extraction resolution:",
        "res_keep": "Keep original",
        "res_only_w": "Width only",
        "res_only_h": "Height only",
        "res_wh": "Width × Height",
        "gpu_check": "Use GPU (if supported) – SIFT extraction & matching",
        "mesh_cb": "Enable mesh reconstruction (very slow, high disk usage)",
        "jpeg_q": "JPEG quality (-qscale:v):",
        "sift_max": "SiftExtraction.max_image_size:",
        "seq_overlap": "SequentialMatching.overlap:",
        "fps_title": "Frame reduction:",
        "fps_all": "All frames",
        "fps_every": "Every",
        "fps_every_suffix": "th frame (e.g., 2 = half the frames)",
        "videos": "Videos",
        "add_videos": "Add videos…",
        "remove_sel": "Remove selected",
        "clear_list": "Clear list",
        "scenes_dir": "Scenes output folder:",
        "start": "Start",
        "test_tools": "Test tools",
        "elapsed": "Elapsed",
        "dlg_pick_dir": "Select folder",
        "dlg_pick_file": "Select file",
        "dlg_pick_videos": "Select videos",
        "dlg_create_structure_title": "Project structure",
        "dlg_create_structure_msg": "Not all expected folders were found.\n\nCreate all required folders now?",
        "dlg_create_structure_where": "Where should the folders be created?",
        "dlg_done": "Done",
        "dlg_structure_created": "Project structure created.",
        "msg_linux_only": "System PATH fallback is active on Linux only.",
        "msg_found": "Found:",
        "msg_found_none": "No additional tools found in PATH.",
        "msg_installer_linux_only": "The tool installer is Linux-focused.",
        "installer_title": "Install tools",
        "installer_what": "What should be installed/built?",
        "installer_ffmpeg": "ffmpeg (package manager)",
        "installer_colmap": "Build COLMAP from source",
        "installer_glomap": "Build GLOMAP from source",
        "installer_source": "Source (Git URL or release archive):",
        "installer_use_cuda": "Use CUDA if available",
        "installer_try_cuda_pkg": "(Optional) Try installing CUDA Toolkit via package manager now",
        "installer_start": "Start installing",
        "installer_close": "Close",
        "installer_note": "Note: Local project install to 01 GLOMAP/<tool>.\nRelease archives (.tar.gz/.zip) are unpacked to 06 Sources/<tool>.",
        "installer_done_ok": "Tools installation completed successfully",
        "installer_done_fail": "Tools installation finished with errors",
        "warn_running": "A run is already active.",
        "warn_no_videos": "Please add at least one video.",
        "err_ffmpeg": "Please select the executable for FFMPEG.",
        "err_colmap": "Please select the executable for COLMAP.",
        "run_extract": "Extracting frames (ffmpeg)…",
        "run_feat": "COLMAP feature_extractor…",
        "run_match": "COLMAP sequential_matcher…",
        "run_mapper": "Sparse reconstruction (mapper)…",
        "run_undistort": "COLMAP image_undistorter…",
        "run_patchmatch": "COLMAP patch_match_stereo…",
        "run_fuse": "COLMAP stereo_fusion…",
        "run_mesher": "Mesh reconstruction (poisson_mesher)…",
        "done_all": "All done.",
        "tools_test_begin": "### Testing tools ###",
        "tools_test_end": "### Test finished ###",
        "lang_label": "Language:",
        "lang_de": "Deutsch",
        "lang_en": "English",
            "info_btn": "Info",
        "about_title": "Info",
        "about_text": "Based on the script by ",
        "about_link": "Polyfjord",
        "about_paypal_btn": "Buy me a coffee via PayPal",
        "dlg_vcredist_title": "VC++ runtime missing",
        "dlg_vcredist_msg": "Microsoft VC++ runtime seems missing. Install now?",
        "dlg_vcredist_info": "Microsoft VC++ runtime must be installed for the script to work, script will exit. After installing the VC++ runtime, run the script again.",
}
}

# ------------------------- small utilities (from working version) -------------------------
# --- Linux Paketmanager-Erkennung ---
# Nur für Systempakete. Downloads/Entpacken ohne sudo.
def _detect_pkg_manager():
    if shutil.which("apt"): return "apt"
    if shutil.which("dnf"): return "dnf"
    if shutil.which("zypper"): return "zypper"
    if shutil.which("pacman"): return "pacman"
    if shutil.which("apk"): return "apk"
    return None

def _read_os_release():
    data = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line: continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"')
                data[k] = v
    except Exception:
        pass
    return data

def _tk_install_command(pm):
    if pm == "apt": return "apt update && apt install -y python3-tk"
    if pm == "dnf": return "dnf install -y python3-tkinter"
    if pm == "zypper": return "zypper --non-interactive install -y python3-tk"
    if pm == "pacman": return "pacman -Sy --noconfirm tk"
    if pm == "apk": return "apk add --no-cache tcl tk"
    return None

def _sudo_wrap(cmd):
    """Return escalated command list or None when no graphical polkit is available."""
    if OS_NAME == "Linux":
        display = os.environ.get("DISPLAY")
        wayland = os.environ.get("WAYLAND_DISPLAY")
        pkexec = shutil.which("pkexec")
        if pkexec and (display or wayland):
            env_args = ["env"]
            # keep GUI session vars so pkexec can talk to the running desktop
            for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
                val = os.environ.get(key)
                if val:
                    env_args.append(f"{key}={val}")
            return [pkexec, *env_args, "bash", "-lc", cmd]
        return None  # no graphical helper detected -> caller must instruct manual install
    if shutil.which("sudo"):
        return ["sudo", "bash", "-lc", cmd]
    return ["bash", "-lc", cmd]

def ensure_tkinter():
    try:
        import importlib; importlib.import_module("tkinter"); return True
    except (ModuleNotFoundError, ImportError):  # also catch missing shared libs raising ImportError
        if OS_NAME != "Linux":
            sys.stderr.write("[Error] Tkinter missing and cannot be auto-installed on this OS.\n")
            return False
        pm = _detect_pkg_manager(); cmd = _tk_install_command(pm) if pm else None
        sys.stderr.write("Tkinter (python3-tk) not found.\n")
        if not cmd:
            sys.stderr.write("No supported package manager detected. Install Tkinter manually.\n")
            return False
        # Ask in terminal (pre-GUI). pkexec will open GUI prompt if available.
        sys.stderr.write(f"Detected package manager: {pm}\nInstall Tkinter now? [Y/n]: ")
        try: choice = input().strip().lower()
        except EOFError: choice = "y"
        if choice in ("", "y", "yes", "j", "ja"):
            wrapped = _sudo_wrap(cmd)
            if wrapped is None:
                # When no graphical helper is present we stop auto-installation and tell the user.
                sys.stderr.write(f"No graphical polkit helper detected. Please run manually:\n  {cmd}\n")
                return False
            sys.stderr.write(f"Invoking package installation via:\n  {' '.join(shlex.quote(x) for x in wrapped)}\n")
            try:
                subprocess.run(wrapped, check=True)
            except subprocess.CalledProcessError as exc:
                sys.stderr.write(f"Installation failed (code {exc.returncode}). Manually run:\n  {cmd}\n")
                return False
            try:
                import importlib; importlib.import_module("tkinter")
                sys.stderr.write("Tkinter installation succeeded. Restarting GUI…\n")
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except (ModuleNotFoundError, ImportError):  # handle libtk import failures as well
                sys.stderr.write("Tkinter still cannot be imported.\n")
                return False
        else:
            sys.stderr.write("Cancelled. Please install Tkinter manually.\n")
            return False
    return True

if not ensure_tkinter():
    sys.exit(1)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = f"AutoTracker GUI (Python) – {OS_NAME}"
DEFAULT_DIRS = {
    "sfm": "01 GLOMAP",
    "videos": "02 VIDEOS",
    "ffmpeg": "03 FFMPEG",
    "scenes": "04 SCENES",
    "sources": "06 Sources",
}

# --- run_cmd ---
# Führt einen Prozess aus, loggt stdout live.
# Windows: setzt Qt/OpenGL Variablen.
# Bei Fehlern: Fallback mit Offscreen + Software OpenGL.
def run_cmd(cmd_list, cwd=None, log_fn=None):
    """Run a command, stream output, and on Windows retry COLMAP if Qt/GL fallback is needed."""
    def _popen(env=None):
        return subprocess.Popen(cmd_list, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, bufsize=1, env=env)
    # Prepare env for first attempt (inject Qt paths for COLMAP/GLOMAP on Windows)
    env = None
    try:
        exe_str = cmd_list[0]
        exe = Path(str(exe_str).strip('"'))
        name = exe.name.lower()
        if os.name == 'nt' and exe.exists() and ('colmap' in name or 'glomap' in name):
            env = os.environ.copy()
            bin_dir = exe.parent
            if 'colmap' in name:
                colmap_root = bin_dir.parent
                plugins_root = colmap_root / 'plugins'
                platforms_dir = plugins_root / 'platforms'
                if not platforms_dir.exists():
                    platforms_dir = bin_dir / 'platforms'
                    plugins_root = bin_dir
                env['QT_PLUGIN_PATH'] = str(plugins_root)
                env['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(platforms_dir)
                env['QT_QPA_PLATFORM'] = 'windows'
                env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH','')
                if log_fn:
                    log_fn(f"[WIN][Qt][COLMAP] plugins={plugins_root} platforms={platforms_dir}")
            else:
                base = bin_dir.parent.parent
                colmap_root = base / 'colmap'
                plugins_root = colmap_root / 'plugins'
                platforms_dir = plugins_root / 'platforms'
                if not platforms_dir.exists():
                    platforms_dir = colmap_root / 'bin' / 'platforms'
                    if not platforms_dir.exists():
                        platforms_dir = bin_dir / 'platforms'
                        plugins_root = bin_dir
                env['QT_PLUGIN_PATH'] = str(plugins_root)
                env['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(platforms_dir)
                env['QT_QPA_PLATFORM'] = 'windows'
                env['PATH'] = str(bin_dir) + os.pathsep + str(colmap_root / 'bin') + os.pathsep + env.get('PATH','')
                if log_fn:
                    log_fn(f"[WIN][Qt][GLOMAP] plugins={plugins_root} platforms={platforms_dir}")
    except Exception:
        pass

    # First run
    try:
        proc = _popen(env)
    except FileNotFoundError as e:
        if log_fn: log_fn(f"[ERROR] {e}")
        return 1
    lines = []
    for line in proc.stdout:
        s = line.rstrip()
        lines.append(s)
        if log_fn: log_fn(s)
    proc.stdout.close()
    rc = proc.wait()

    # If failed on Windows with typical Qt/GL missing libs, retry offscreen/software
    if rc != 0 and os.name == 'nt':
        joined = '\n'.join(lines)
        if any(k in joined for k in ['Failed to load libEGL', 'Failed to load opengl32sw', 'WGL/OpenGL functions', 'opengl_utils.cc']):
            if log_fn: log_fn('[WIN][Qt] Fallback: retry offscreen + software OpenGL')
            env2 = (env or os.environ).copy()
            env2['QT_QPA_PLATFORM'] = 'offscreen'
            env2['QT_OPENGL'] = 'software'
            try:
                proc2 = _popen(env2)
                for line in proc2.stdout:
                    s = line.rstrip()
                    if log_fn: log_fn(s)
                proc2.stdout.close()
                rc2 = proc2.wait()
                return rc2
            except Exception as e:
                if log_fn: log_fn(f"[WIN][Qt] Fallback start failed: {e}")
                return rc
    return rc


def run_and_capture(cmd_list, cwd=None):
    try:
        res = subprocess.run(cmd_list, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return res.returncode, res.stdout or ""
    except FileNotFoundError as e:
        return 127, str(e)
    except PermissionError as e:
        return 126, str(e)
    except Exception as e:
        return 125, str(e)

def which_first(names):
    for n in names:
        p = shutil.which(n)
        if p: return p
    return None

def detect_cuda():
    return bool(shutil.which("nvcc") or shutil.which("nvidia-smi") or Path("/usr/local/cuda").exists())

# --- Systemweite Paketinstallation ---
# Führt Installation mit sudo/pkexec aus (nur Systempakete).
def pkg_missing(pm, pkgs, log_fn):
    """Return list of packages not yet installed."""
    missing = []
    for pkg in pkgs:
        if pm == "apt":
            cmd = ["dpkg", "-s", pkg]
        elif pm in ("dnf", "zypper"):
            cmd = ["rpm", "-q", pkg]
        elif pm == "pacman":
            cmd = ["pacman", "-Qi", pkg]
        elif pm == "apk":
            cmd = ["apk", "info", "-e", pkg]
        else:
            missing.append(pkg)
            continue
        # Rootless check: hide output, only look at return code
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            log_fn(f"[pkg] {pkg} bereits installiert")
        else:
            missing.append(pkg)
    return missing

def pkg_install(pm, pkgs, log_fn):
    if pm is None or not pkgs:
        return 1
    pkgs = pkg_missing(pm, pkgs, log_fn)
    if not pkgs:
        log_fn("[pkg] alle Pakete bereits installiert")
        return 0
    if pm == "apt":
        cmd = f"apt update && apt install -y {' '.join(pkgs)}"
    elif pm == "dnf":
        cmd = f"dnf install -y {' '.join(pkgs)}"
    elif pm == "zypper":
        cmd = f"zypper --non-interactive install -y {' '.join(pkgs)}"
    elif pm == "pacman":
        cmd = f"pacman -Sy --noconfirm {' '.join(pkgs)}"
    elif pm == "apk":
        cmd = f"apk add --no-cache {' '.join(pkgs)}"
    else:
        return 1
    log_fn(f"[pkg] {cmd}")
    wrapped = _sudo_wrap(cmd)
    if wrapped is None:
        # Without pkexec (graphical helper) we cannot elevate automatically.
        log_fn(f"[pkg] Kein grafischer Polkit-Helfer gefunden. Bitte manuell ausführen: {cmd}")
        return 1
    return subprocess.run(wrapped).returncode

def log_cmd(cmd, log_fn, cwd=None):
    txt = " ".join(shlex.quote(str(c)) for c in cmd)
    if cwd: txt += f"  (cwd={cwd})"
    log_fn(txt)

def _unique_preserve_order(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out



# ---- Download + Entpacken von Release-Archiven (tar.gz/zip) ----
def is_archive_url(url: str) -> bool:
    u = url.lower()
    return u.endswith(".tar.gz") or u.endswith(".tgz") or u.endswith(".zip")

def download_file(url: str, dest_file: Path, log_fn, progress_cb=None) -> bool:

    try:
        log_fn(f"[dl] Lade {url} …")
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        # 1) urllib + certifi-Context
        try:
            try:
                import certifi
                cafile = certifi.where()
                ctx = ssl.create_default_context(cafile=cafile)
            except Exception:
                # try to install certifi on Windows if missing
                if platform.system() == "Windows":
                    try:
                        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--upgrade", "pip", "certifi"], check=False)
                        import importlib; certifi = importlib.import_module("certifi")
                        ctx = ssl.create_default_context(cafile=certifi.where())
                    except Exception:
                        ctx = ssl.create_default_context()
                else:
                    ctx = ssl.create_default_context()
            with urllib.request.urlopen(url, context=ctx, timeout=120) as r, open(dest_file, "wb") as f:
                total = int(r.headers.get("Content-Length", 0)) or 0
                downloaded = 0
                while True:
                    chunk = r.read(1024 * 512)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(total, downloaded)
            log_fn(f"[dl] Gespeichert: {dest_file}")
            return True
        except Exception as e1:
            log_fn(f"[dl] urllib Fehler: {e1}")

        # 2) curl Fallback (Windows 10+ hat curl)
        curl = shutil.which("curl")
        if curl:
            try:
                cmd = [curl, "-L", url, "-o", str(dest_file)]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
                if res.returncode == 0 and dest_file.exists() and dest_file.stat().st_size > 0:
                    log_fn("[dl] Download via curl erfolgreich.")
                    return True
                else:
                    log_fn(f"[dl] curl Fehler (rc={res.returncode}): {res.stdout[-400:]}")
            except Exception as e2:
                log_fn(f"[dl] curl Exception: {e2}")

        # 3) PowerShell Fallback (erzwinge TLS1.2)
        if platform.system() == "Windows":
            ps = shutil.which("powershell") or shutil.which("pwsh")
            if ps:
                try:
                    ps_script = (
                        "[Net.ServicePointManager]::SecurityProtocol = "
                        "[Net.SecurityProtocolType]::Tls12 -bor "
                        "[Net.SecurityProtocolType]::Tls11 -bor "
                        "[Net.SecurityProtocolType]::Tls; "
                        f"Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile '{str(dest_file)}'"
                    )
                    res = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
                    if res.returncode == 0 and dest_file.exists() and dest_file.stat().st_size > 0:
                        log_fn("[dl] Download via PowerShell erfolgreich.")
                        return True
                    else:
                        log_fn(f"[dl] PowerShell Fehler (rc={res.returncode}): {res.stdout[-400:]}")
                except Exception as e3:
                    log_fn(f"[dl] PowerShell Exception: {e3}")

        log_fn("[dl] Alle Download-Methoden fehlgeschlagen.")
        return False
    except Exception as e:
        log_fn(f"[dl] Fehler: {e}")
        return False


def extract_archive(archive: Path, target_dir: Path, log_fn) -> Path | None:
    try:
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_extract = target_dir.parent / (target_dir.name + "_extract_tmp")
        if tmp_extract.exists(): shutil.rmtree(tmp_extract, ignore_errors=True)
        tmp_extract.mkdir(parents=True, exist_ok=True)
        if str(archive).lower().endswith((".tar.gz",".tgz")):
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(tmp_extract)
        elif str(archive).lower().endswith(".zip"):
            with zipfile.ZipFile(archive, "r") as z:
                z.extractall(tmp_extract)
        else:
            log_fn(f"[dl] Unbekanntes Archivformat: {archive}")
            return None
        entries = list(tmp_extract.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            shutil.move(str(entries[0]), str(target_dir))
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            for e in entries:
                shutil.move(str(e), str(target_dir))
        shutil.rmtree(tmp_extract, ignore_errors=True)
        log_fn(f"[dl] Entpackt nach: {target_dir}")
        return target_dir
    except Exception as e:
        log_fn(f"[dl] Entpacken fehlgeschlagen: {e}")
        return None

def ensure_source_from_url(url: str, dest_dir: Path, log_fn) -> Path | None:
    if is_archive_url(url):
        filename = url.split("/")[-1]
        archive_path = dest_dir.parent / filename
        if archive_path.exists():
            try: archive_path.unlink()
            except Exception: pass
        ok = download_file(url, archive_path, log_fn)
        if not ok: return None
        src = extract_archive(archive_path, dest_dir, log_fn)
        try: archive_path.unlink()
        except Exception: pass
        return src
    else:
        return ensure_git_clone_or_refresh(url, dest_dir, "", log_fn) == 0 and dest_dir or None

# ---- Git fallback ----
def ensure_git_clone_or_refresh(url: str, dest: Path, branch: str, log_fn):
    dest = Path(dest)
    if dest.exists() and not (dest / ".git").is_dir():
        log_fn(f"[git] Ziel existiert, ist aber kein Git-Repo: {dest} → entferne Ordner…")
        try: shutil.rmtree(dest)
        except Exception as e:
            log_fn(f"[git] Entfernen fehlgeschlagen: {e}")
            return 1
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone", url, str(dest)]; log_cmd(cmd, log_fn)
        code = run_cmd(cmd, log_fn=log_fn)
        if code != 0: return code
    cmd = ["git", "-C", str(dest), "fetch", "--all", "--tags"]; log_cmd(cmd, log_fn); run_cmd(cmd, log_fn=log_fn)
    if branch and ("://" not in branch) and (not branch.endswith(".git")):
        cmd = ["git", "-C", str(dest), "checkout", branch]; log_cmd(cmd, log_fn); run_cmd(cmd, log_fn=log_fn)
    cmd = ["git", "-C", str(dest), "pull", "--ff-only"]; log_cmd(cmd, log_fn); return run_cmd(cmd, log_fn=log_fn)

def cmake_configure_ninja(src, build_dir, log_fn, extra_args=None):
    build_dir = Path(build_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    args = extra_args or []
    cfg = ["cmake", "-S", str(src), "-B", str(build_dir), "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"] + args
    log_cmd(cfg, log_fn)
    return run_cmd(cfg, log_fn=log_fn)

def ninja_build(build_dir, log_fn):
    cmd = ["ninja"]; log_cmd(cmd, log_fn, cwd=build_dir); return run_cmd(cmd, cwd=str(build_dir), log_fn=log_fn)

def ninja_install(build_dir, log_fn):
    cmd = ["ninja", "install"]; log_cmd(cmd, log_fn, cwd=build_dir); return run_cmd(cmd, cwd=str(build_dir), log_fn=log_fn)

def find_binary(root, names):
    root = Path(root)
    best = None; best_depth = 10**9
    for dirpath, dirnames, filenames in os.walk(root):
        for n in names:
            if n in filenames:
                p = Path(dirpath) / n
                depth = len(Path(dirpath).parts)
                if depth < best_depth:
                    best = p; best_depth = depth
    return best

def ensure_binary_installed(bin_expected: Path, build_dir: Path, binary_name: str, log_fn):
    try: bin_expected.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e: log_fn(f"[INSTALL] Konnte Zielordner nicht erstellen: {bin_expected.parent} ({e})")
    if bin_expected.exists():
        try: os.chmod(bin_expected, 0o755)
        except Exception: pass
        return True
    candidate = find_binary(build_dir, [binary_name])
    if candidate and Path(candidate).exists():
        try:
            shutil.copy2(candidate, bin_expected); os.chmod(bin_expected, 0o755)
            log_fn(f"[INSTALL] Binary via Fallback kopiert: {candidate} -> {bin_expected}")
            return True
        except Exception as e:
            log_fn(f"[INSTALL] Fallback-Kopie fehlgeschlagen: {e}")
    else:
        log_fn(f"[INSTALL] Fallback: Binary {binary_name} nicht im Build-Ordner gefunden.")
    return False

# ---- CUDA/GCC-Heuristik ----
def _get_version_output(prog):
    try:
        res = subprocess.run([prog, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if res.returncode == 0:
            return res.stdout or ""
    except Exception:
        pass
    return ""

def _detect_nvcc_gcc_combo():
    nvcc_out = _get_version_output("nvcc")
    gxx_out = _get_version_output("g++")
    nvcc_major = None; nvcc_minor = None
    import re
    m = re.search(r"release\s+(\d+)\.(\d+)", nvcc_out or "", re.I)
    if m:
        nvcc_major, nvcc_minor = int(m.group(1)), int(m.group(2))
    gxx_major = None
    m2 = re.search(r"g\+\+\s+\(.*\)\s+(\d+)\.", gxx_out or "")
    if m2:
        gxx_major = int(m2.group(1))
    return (nvcc_major, nvcc_minor, gxx_major)

# --- CUDA/GCC Heuristik ---
# nvcc 12.x inkompatibel mit g++ >=13. Versucht g++-12.
def _maybe_cuda_host_flag(pm, log_fn):
    nvcc_major, nvcc_minor, gxx_major = _detect_nvcc_gcc_combo()
    if nvcc_major is None or gxx_major is None:
        return []
    if nvcc_major == 12 and (gxx_major is not None and gxx_major >= 13):
        from shutil import which
        host = which("g++-12")
        if host is None and pm == "apt":
            log_fn("[INSTALL] g++-12 nicht gefunden – versuche Installation (apt)…")
            pkg_install(pm, ["gcc-12", "g++-12"], log_fn)
            host = which("g++-12")
        if host:
            log_fn(f"[INSTALL] Setze CUDA Host-Compiler: {host}")
            return [f"-DCMAKE_CUDA_HOST_COMPILER={host}", "-DCUDA_ENABLED=ON"]
        else:
            log_fn("[INSTALL] Warnung: g++-12 nicht verfügbar. Fallback auf CPU-Build (CUDA wird deaktiviert).")
            return ["-DCUDA_ENABLED=OFF"]
    return ["-DCUDA_ENABLED=ON"]

# ----------------------------- GUI helpers -----------------------------
def find_in_subdir_with_bin(top: Path, subdir: str, names):
    base = top / subdir
    for n in names:
        p = base / n
        if p.exists(): return str(p.resolve())
    bin_dir = base / "bin"
    for n in names:
        p = bin_dir / n
        if p.exists(): return str(p.resolve())
    return None

def find_in_nested_subdir_with_bin(top: Path, base_subdir: str, program_subdir: str, names):
    base = top / base_subdir / program_subdir
    for n in names:
        p = base / n
        if p.exists(): return str(p.resolve())
    bin_dir = base / "bin"
    for n in names:
        p = bin_dir / n
        if p.exists(): return str(p.resolve())
    return None

def looks_like_05_script(name: str) -> bool:
    s = name.strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    return s in ("05script", "05scripts", "05scriptfolder")

class PlaceholderEntry(ttk.Entry):
    def __init__(self, master=None, placeholder="", textvariable=None, **kw):
        super().__init__(master, textvariable=textvariable, **kw)
        self._placeholder = placeholder; self._placeholder_active = False
        self._normal_fg = self.cget("foreground") if "foreground" in self.keys() else None
        self._placeholder_fg = "#888"
        self._var = textvariable if textvariable is not None else tk.StringVar()
        if textvariable is None: self.configure(textvariable=self._var)
        self.bind("<FocusIn>", self._clear_placeholder); self.bind("<FocusOut>", self._add_placeholder_if_empty)
        self._add_placeholder_if_empty()

    def set_text(self, text: str):
        self._placeholder_active = False; self.configure(foreground=self._normal_fg); self._var.set(text)

    def set_placeholder(self, text: str):
        self._placeholder = text; self._add_placeholder_if_empty()

    def get_text(self) -> str:
        return "" if self._placeholder_active else self._var.get()

    def _clear_placeholder(self, *_):
        if self._placeholder_active:
            self._var.set(""); self.configure(foreground=self._normal_fg); self._placeholder_active = False

    def _add_placeholder_if_empty(self, *_):
        if not self._var.get():
            self._placeholder_active = True; self.configure(foreground=self._placeholder_fg); self._var.set(self._placeholder)

# === AutoTrackerGUI ===
# Haupt-GUI. Layout und Funktion bleiben unverändert.
class AutoTrackerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        # language
        self.lang = detect_lang()
        self.S = I18N[self.lang]

        self.title(self.S["app_title"].format(os=OS_NAME))
        self.geometry("1120x930"); self.minsize(1000, 830)
        self._worker = None; self._stop_flag = False; self._elapsed_start = None; self._elapsed_job = None

        # --- top bar with language dropdown ---
        topbar = ttk.Frame(self); topbar.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(topbar, text=self.S["lang_label"]).pack(side="left")
        self.lang_var = tk.StringVar(value=self.S["lang_de"] if self.lang=="de" else self.S["lang_en"])
        self.lang_combo = ttk.Combobox(topbar, width=12, state="readonly",
                                       values=[I18N["de"]["lang_de"], I18N["en"]["lang_en"]],
                                       textvariable=self.lang_var)
        self.lang_combo.pack(side="left", padx=(6, 0))
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_lang_changed)
        self.info_btn = ttk.Button(topbar, text=self.S["info_btn"], command=self._open_about_dialog)
        self.info_btn.pack(side="right")

        # --- paths & tools ---
        self.settings = load_settings()  # load persisted settings
        self.paths_frame = ttk.LabelFrame(self, text=self.S["paths_tools"]); self.paths_frame.pack(fill="x", padx=10, pady=(10, 6))
        script_dir = Path(__file__).resolve().parent; parent = script_dir.parent
        if looks_like_05_script(script_dir.name) or (parent / DEFAULT_DIRS["sfm"]).exists() or (parent / DEFAULT_DIRS["ffmpeg"]).exists():
            top_candidate = parent
        else: top_candidate = script_dir
        top_candidate = Path(self.settings.get("top_dir") or top_candidate)  # use saved top_dir if present
        self.top_dir_var = tk.StringVar(value=str(top_candidate))

        row = 0
        self.lbl_project_top = ttk.Label(self.paths_frame, text=self.S["project_top"])
        self.lbl_project_top.grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.top_entry = ttk.Entry(self.paths_frame, textvariable=self.top_dir_var, width=80); self.top_entry.grid(row=row, column=1, sticky="we", padx=(0, 6), pady=6)
        self.paths_frame.grid_columnconfigure(1, weight=1)
        top_btns = ttk.Frame(self.paths_frame); top_btns.grid(row=row, column=2, padx=6, pady=6, sticky="e")
        self.btn_browse_top = ttk.Button(top_btns, text=self.S["browse"], command=lambda: self._browse(self.top_dir_var, is_dir=True)); self.btn_browse_top.pack(side="left")
        self.btn_redetect = ttk.Button(top_btns, text=self.S["rediscover"], command=self._auto_detect_tools); self.btn_redetect.pack(side="left", padx=(6, 0))
        row += 1

        os_frame = ttk.Frame(self.paths_frame); os_frame.grid(row=row, column=0, columnspan=3, sticky="we", padx=8, pady=(0, 6))
        osr = _read_os_release() if OS_NAME == "Linux" else {}; distro = f"{osr.get('NAME','')} {osr.get('VERSION','')}".strip()
        self.lbl_os = ttk.Label(os_frame, text=self.S["os_detected"].format(os=OS_NAME, distro=('– ' + distro) if distro else '')); self.lbl_os.pack(side="left")
        self.use_path_linux_var = tk.BooleanVar(value=True)  # default True: auto PATH fallback if not found
        self.cb_search_path = ttk.Checkbutton(os_frame, text=self.S["search_path_cb"], variable=self.use_path_linux_var); self.cb_search_path.pack(side="left", padx=(12, 0))
        self.search_path_btn = ttk.Button(os_frame, text=self.S["search_path_btn"], command=self._detect_from_system_path); self.search_path_btn.pack(side="left", padx=(12, 0))
        self.install_tools_btn = ttk.Button(os_frame, text=self.S["install_tools"], command=self._open_installer_dialog); self.install_tools_btn.pack(side="left", padx=(12, 0))
        if IS_WINDOWS or OS_NAME != "Linux":
            self.cb_search_path.state(["disabled"]); self.search_path_btn.state(["disabled"])
            if OS_NAME not in ("Linux", "Windows"): self.install_tools_btn.state(["disabled"])
        row += 1

        self.ffmpeg_placeholder = self.S["ffmpeg_placeholder"]
        self.colmap_placeholder = self.S["colmap_placeholder"]
        self.glomap_placeholder = self.S["glomap_placeholder"]

        self.lbl_ffmpeg = ttk.Label(self.paths_frame, text=self.S["ffmpeg_label"]); self.lbl_ffmpeg.grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.ffmpeg_var = tk.StringVar(); self.ffmpeg_entry = PlaceholderEntry(self.paths_frame, placeholder=self.ffmpeg_placeholder, textvariable=self.ffmpeg_var, width=80)
        self.ffmpeg_entry.grid(row=row, column=1, sticky="we", padx=(0, 6), pady=6)
        self.btn_ffmpeg_browse = ttk.Button(self.paths_frame, text=self.S["browse"], command=lambda: self._browse_exe(self.ffmpeg_entry)); self.btn_ffmpeg_browse.grid(row=row, column=2, padx=6, pady=6)
        row += 1

        self.lbl_colmap = ttk.Label(self.paths_frame, text=self.S["colmap_label"]); self.lbl_colmap.grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.colmap_var = tk.StringVar(); self.colmap_entry = PlaceholderEntry(self.paths_frame, placeholder=self.colmap_placeholder, textvariable=self.colmap_var, width=80)
        self.colmap_entry.grid(row=row, column=1, sticky="we", padx=(0, 6), pady=6)
        self.btn_colmap_browse = ttk.Button(self.paths_frame, text=self.S["browse"], command=lambda: self._browse_exe(self.colmap_entry)); self.btn_colmap_browse.grid(row=row, column=2, padx=6, pady=6)
        row += 1

        self.lbl_glomap = ttk.Label(self.paths_frame, text=self.S["glomap_label"]); self.lbl_glomap.grid(row=row, column=0, sticky="w", padx=8, pady=6)
        self.glomap_var = tk.StringVar(); self.glomap_entry = PlaceholderEntry(self.paths_frame, placeholder=self.glomap_placeholder, textvariable=self.glomap_var, width=80)
        self.glomap_entry.grid(row=row, column=1, sticky="we", padx=(0, 6), pady=6)
        self.btn_glomap_browse = ttk.Button(self.paths_frame, text=self.S["browse"], command=lambda: self._browse_exe(self.glomap_entry)); self.btn_glomap_browse.grid(row=row, column=2, padx=6, pady=6)
        row += 1

        # --- options frame ---
        self.opts_frame = ttk.LabelFrame(self, text=self.S["options"]); self.opts_frame.pack(fill="x", padx=10, pady=6)
        self.res_mode = tk.StringVar(value="keep"); self.width_var = tk.StringVar(value=""); self.height_var = tk.StringVar(value="")
        res_frame = ttk.Frame(self.opts_frame); res_frame.pack(fill="x", padx=8, pady=6)
        self.lbl_res_title = ttk.Label(res_frame, text=self.S["res_title"]); self.lbl_res_title.grid(row=0, column=0, sticky="w")
        self.rb_keep = ttk.Radiobutton(res_frame, text=self.S["res_keep"], variable=self.res_mode, value="keep"); self.rb_keep.grid(row=1, column=0, sticky="w")
        self.rb_w = ttk.Radiobutton(res_frame, text=self.S["res_only_w"], variable=self.res_mode, value="w"); self.rb_w.grid(row=1, column=1, sticky="w")
        self.entry_w = ttk.Entry(res_frame, width=8, textvariable=self.width_var); self.entry_w.grid(row=1, column=2, sticky="w", padx=(4, 12))
        self.rb_h = ttk.Radiobutton(res_frame, text=self.S["res_only_h"], variable=self.res_mode, value="h"); self.rb_h.grid(row=1, column=3, sticky="w")
        self.entry_h = ttk.Entry(res_frame, width=8, textvariable=self.height_var); self.entry_h.grid(row=1, column=4, sticky="w", padx=(4, 12))
        self.rb_wh = ttk.Radiobutton(res_frame, text=self.S["res_wh"], variable=self.res_mode, value="wh"); self.rb_wh.grid(row=1, column=5, sticky="w")
        self.entry_w2 = ttk.Entry(res_frame, width=8, textvariable=self.width_var); self.entry_w2.grid(row=1, column=6, sticky="w", padx=(4, 2))
        ttk.Label(res_frame, text="×").grid(row=1, column=7, sticky="w")
        self.entry_h2 = ttk.Entry(res_frame, width=8, textvariable=self.height_var); self.entry_h2.grid(row=1, column=8, sticky="w", padx=(2, 0))

        self.use_gpu_var = tk.BooleanVar(value=True)
        gpu_frame = ttk.Frame(self.opts_frame); gpu_frame.pack(fill="x", padx=8, pady=(0, 6))
        self.cb_gpu = ttk.Checkbutton(gpu_frame, text=self.S["gpu_check"], variable=self.use_gpu_var); self.cb_gpu.grid(row=0, column=0, sticky="w")

        more_opts = ttk.Frame(self.opts_frame); more_opts.pack(fill="x", padx=8, pady=(0, 6))
        self.jpeg_q_var = tk.StringVar(value="2"); self.sift_max_img_var = tk.StringVar(value="4096"); self.seq_overlap_var = tk.StringVar(value="15")
        self.lbl_jpeg = ttk.Label(more_opts, text=self.S["jpeg_q"]); self.lbl_jpeg.grid(row=0, column=0, sticky="w")
        ttk.Entry(more_opts, width=6, textvariable=self.jpeg_q_var).grid(row=0, column=1, sticky="w", padx=(4, 16))
        self.lbl_sift = ttk.Label(more_opts, text=self.S["sift_max"]); self.lbl_sift.grid(row=0, column=2, sticky="w")
        ttk.Entry(more_opts, width=8, textvariable=self.sift_max_img_var).grid(row=0, column=3, sticky="w", padx=(4, 16))
        self.lbl_overlap = ttk.Label(more_opts, text=self.S["seq_overlap"]); self.lbl_overlap.grid(row=0, column=4, sticky="w")
        ttk.Entry(more_opts, width=6, textvariable=self.seq_overlap_var).grid(row=0, column=5, sticky="w", padx=(4, 16))
        self.mesh_var = tk.BooleanVar(value=False)
        self.cb_mesh = ttk.Checkbutton(more_opts, text=self.S["mesh_cb"], variable=self.mesh_var)
        self.cb_mesh.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4,0))

        self.fps_mode = tk.StringVar(value="all"); self.every_n_var = tk.StringVar(value="2")
        fps_frame = ttk.Frame(self.opts_frame); fps_frame.pack(fill="x", padx=8, pady=(0, 6))
        self.lbl_fps = ttk.Label(fps_frame, text=self.S["fps_title"]); self.lbl_fps.grid(row=0, column=0, sticky="w")
        self.rb_all = ttk.Radiobutton(fps_frame, text=self.S["fps_all"], variable=self.fps_mode, value="all"); self.rb_all.grid(row=1, column=0, sticky="w")
        self.rb_every = ttk.Radiobutton(fps_frame, text=self.S["fps_every"], variable=self.fps_mode, value="every"); self.rb_every.grid(row=1, column=1, sticky="w")
        self.entry_every = ttk.Entry(fps_frame, width=4, textvariable=self.every_n_var); self.entry_every.grid(row=1, column=2, sticky="w", padx=(4, 2))
        self.lbl_every_suf = ttk.Label(fps_frame, text=self.S["fps_every_suffix"]); self.lbl_every_suf.grid(row=1, column=3, sticky="w")

        # --- videos list ---
        self.videos_frame = ttk.LabelFrame(self, text=self.S["videos"]); self.videos_frame.pack(fill="both", expand=True, padx=10, pady=6)
        self.video_list = tk.Listbox(self.videos_frame, selectmode="extended"); self.video_list.pack(fill="both", expand=True, side="left", padx=(8, 0), pady=8)
        btns = ttk.Frame(self.videos_frame); btns.pack(side="left", fill="y", padx=8, pady=8)
        self.btn_add_videos = ttk.Button(btns, text=self.S["add_videos"], command=self.add_videos); self.btn_add_videos.pack(fill="x", pady=(0, 4))
        self.btn_remove_sel = ttk.Button(btns, text=self.S["remove_sel"], command=self.remove_selected); self.btn_remove_sel.pack(fill="x")
        self.btn_clear_list = ttk.Button(btns, text=self.S["clear_list"], command=self.clear_videos); self.btn_clear_list.pack(fill="x", pady=(4, 0))

        self.scenes_dir_var = tk.StringVar(value=str(Path(self.top_dir_var.get()) / DEFAULT_DIRS["scenes"]))
        out_frame = ttk.Frame(self); out_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.lbl_scenes = ttk.Label(out_frame, text=self.S["scenes_dir"]); self.lbl_scenes.pack(side="left")
        ttk.Entry(out_frame, textvariable=self.scenes_dir_var).pack(side="left", fill="x", expand=True, padx=8)
        self.btn_browse_scenes = ttk.Button(out_frame, text=self.S["browse"], command=lambda: self._browse_dir(self.scenes_dir_var)); self.btn_browse_scenes.pack(side="left")

        run_frame = ttk.Frame(self); run_frame.pack(fill="x", padx=10, pady=(6, 6))
        self.run_btn = ttk.Button(run_frame, text=self.S["start"], command=self.start_run); self.run_btn.pack(side="left")
        self.btn_test = ttk.Button(run_frame, text=self.S["test_tools"], command=self.test_tools); self.btn_test.pack(side="left", padx=(8, 0))
        self.elapsed_prefix = self.S["elapsed"]
        self.elapsed_var = tk.StringVar(value=f"{self.elapsed_prefix}: 00:00:00"); ttk.Label(run_frame, textvariable=self.elapsed_var).pack(side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(run_frame, mode="determinate"); self.progress.pack(side="left", fill="x", expand=True, padx=10)

        self.log = tk.Text(self, height=16, wrap="word"); self.log.pack(fill="both", expand=False, padx=10, pady=(6, 10))
        self.top_dir_var.trace_add("write", self._on_top_changed)
        self._maybe_offer_create_structure(); self._auto_detect_tools(); self.load_existing_videos()  # populate video list

    # ---- language handlers ----
    def _on_lang_changed(self, *_):
        val = self.lang_var.get()
        if val == I18N["de"]["lang_de"]: self.lang = "de"
        else: self.lang = "en"
        self.S = I18N[self.lang]
        self._apply_i18n()

    def _apply_i18n(self):
        try:
            self.info_btn.configure(text=self.S["info_btn"])
        except Exception:
            pass
        self.title(self.S["app_title"].format(os=OS_NAME))
        self.paths_frame.configure(text=self.S["paths_tools"])
        self.lbl_project_top.configure(text=self.S["project_top"])
        self.btn_browse_top.configure(text=self.S["browse"])
        self.btn_redetect.configure(text=self.S["rediscover"])

        osr = _read_os_release() if OS_NAME == "Linux" else {}; distro = f"{osr.get('NAME','')} {osr.get('VERSION','')}".strip()
        self.lbl_os.configure(text=self.S["os_detected"].format(os=OS_NAME, distro=('– ' + distro) if distro else ''))
        self.cb_search_path.configure(text=self.S["search_path_cb"])
        self.search_path_btn.configure(text=self.S["search_path_btn"])
        self.install_tools_btn.configure(text=self.S["install_tools"])

        # placeholders
        self.ffmpeg_placeholder = self.S["ffmpeg_placeholder"]
        self.colmap_placeholder = self.S["colmap_placeholder"]
        self.glomap_placeholder = self.S["glomap_placeholder"]
        if not self.ffmpeg_entry.get_text(): self.ffmpeg_entry.set_placeholder(self.ffmpeg_placeholder)
        if not self.colmap_entry.get_text(): self.colmap_entry.set_placeholder(self.colmap_placeholder)
        if not self.glomap_entry.get_text(): self.glomap_entry.set_placeholder(self.glomap_placeholder)

        self.lbl_ffmpeg.configure(text=self.S["ffmpeg_label"]); self.btn_ffmpeg_browse.configure(text=self.S["browse"])
        self.lbl_colmap.configure(text=self.S["colmap_label"]); self.btn_colmap_browse.configure(text=self.S["browse"])
        self.lbl_glomap.configure(text=self.S["glomap_label"]); self.btn_glomap_browse.configure(text=self.S["browse"])

        self.opts_frame.configure(text=self.S["options"])
        self.lbl_res_title.configure(text=self.S["res_title"])
        self.rb_keep.configure(text=self.S["res_keep"])
        self.rb_w.configure(text=self.S["res_only_w"])
        self.rb_h.configure(text=self.S["res_only_h"])
        self.rb_wh.configure(text=self.S["res_wh"])
        self.cb_gpu.configure(text=self.S["gpu_check"])
        self.lbl_jpeg.configure(text=self.S["jpeg_q"])
        self.lbl_sift.configure(text=self.S["sift_max"])
        self.lbl_overlap.configure(text=self.S["seq_overlap"])
        self.cb_mesh.configure(text=self.S["mesh_cb"])
        self.lbl_fps.configure(text=self.S["fps_title"])
        self.rb_all.configure(text=self.S["fps_all"])
        self.rb_every.configure(text=self.S["fps_every"])
        self.lbl_every_suf.configure(text=self.S["fps_every_suffix"])

        self.videos_frame.configure(text=self.S["videos"])
        self.btn_add_videos.configure(text=self.S["add_videos"])
        self.btn_remove_sel.configure(text=self.S["remove_sel"])
        self.btn_clear_list.configure(text=self.S["clear_list"])

        self.lbl_scenes.configure(text=self.S["scenes_dir"])
        self.btn_browse_scenes.configure(text=self.S["browse"])

        self.run_btn.configure(text=self.S["start"])
        self.btn_test.configure(text=self.S["test_tools"])

        self.elapsed_prefix = self.S["elapsed"]
        # update displayed string but keep time value
        try:
            cur = self.elapsed_var.get()
            # replace prefix before colon
            if ":" in cur:
                suffix = cur.split(":", 1)[1].strip()
                self.elapsed_var.set(f"{self.elapsed_prefix}: {suffix}")
            else:
                self.elapsed_var.set(f"{self.elapsed_prefix}: 00:00:00")
        except Exception:
            self.elapsed_var.set(f"{self.elapsed_prefix}: 00:00:00")

    # ---- UI helper ----
    def _browse(self, var, is_dir=False):
        title = self.S["dlg_pick_dir"] if is_dir else self.S["dlg_pick_file"]
        val = filedialog.askdirectory(title=title) if is_dir else filedialog.askopenfilename(title=title)
        if val: var.set(val)

    def _browse_exe(self, entry: PlaceholderEntry):
        val = filedialog.askopenfilename(title=self.S["dlg_pick_file"])
        if val: entry.set_text(str(Path(val).resolve()))

    def _browse_dir(self, var):
        val = filedialog.askdirectory(title=self.S["dlg_pick_dir"])
        if val: var.set(val)

    def _on_top_changed(self, *args):
        top = Path(self.top_dir_var.get())
        self.scenes_dir_var.set(str(top / DEFAULT_DIRS["scenes"]))
        self._auto_detect_tools()
        self.settings["top_dir"] = str(top)  # persist selected top_dir
        save_settings(self.settings)
        self.clear_videos(); self.load_existing_videos()  # refresh video list

    def _project_missing_dirs(self, top: Path):
        base_dirs = [top / DEFAULT_DIRS["sfm"], top / DEFAULT_DIRS["videos"], top / DEFAULT_DIRS["ffmpeg"], top / DEFAULT_DIRS["scenes"], top / DEFAULT_DIRS["sources"]]
        sub_dirs = [top / DEFAULT_DIRS["sfm"] / "colmap" / "bin",
                    top / DEFAULT_DIRS["sfm"] / "glomap" / "bin",
                    top / DEFAULT_DIRS["ffmpeg"] / "bin",
                    top / DEFAULT_DIRS["sources"] / "colmap",
                    top / DEFAULT_DIRS["sources"] / "glomap"]
        return [d for d in base_dirs + sub_dirs if not d.exists()]

    def _create_project_structure(self, base: Path):
        dirs = [base / DEFAULT_DIRS["sfm"], base / DEFAULT_DIRS["videos"], base / DEFAULT_DIRS["ffmpeg"], base / DEFAULT_DIRS["scenes"], base / DEFAULT_DIRS["sources"],
                base / DEFAULT_DIRS["sfm"] / "colmap" / "bin", base / DEFAULT_DIRS["sfm"] / "glomap" / "bin", base / DEFAULT_DIRS["ffmpeg"] / "bin",
                base / DEFAULT_DIRS["sources"] / "colmap", base / DEFAULT_DIRS["sources"] / "glomap"]
        for d in dirs: d.mkdir(parents=True, exist_ok=True)

    def _maybe_offer_create_structure(self):
        if not self.settings.get("ask_create_structure", True): return  # user opted out
        top = Path(self.top_dir_var.get()); missing = self._project_missing_dirs(top)
        if not missing: return
        create = messagebox.askyesno(self.S["dlg_create_structure_title"], self.S["dlg_create_structure_msg"])
        self.settings["ask_create_structure"] = create; save_settings(self.settings)
        if not create: return
        base_dir = filedialog.askdirectory(title=self.S["dlg_create_structure_where"], initialdir=str(top))
        if not base_dir: return
        base = Path(base_dir); self._create_project_structure(base)
        self.top_dir_var.set(str(base)); self.scenes_dir_var.set(str(base / DEFAULT_DIRS["scenes"]))
        self._auto_detect_tools(); messagebox.showinfo(self.S["dlg_done"], self.S["dlg_structure_created"])

    def _auto_detect_tools(self):
        top = Path(self.top_dir_var.get())
        ff_names = ["ffmpeg.exe", "ffmpeg"] if IS_WINDOWS else ["ffmpeg"]
        cm_names = ["colmap.exe", "colmap"] if IS_WINDOWS else ["colmap"]
        gm_names = ["glomap.exe", "glomap"] if IS_WINDOWS else ["glomap"]

        ff_path = find_in_subdir_with_bin(top, DEFAULT_DIRS["ffmpeg"], ff_names)
        # also check nested '03 FFMPEG/bin' which find_in_subdir_with_bin already covers; but keep PATH fallback auto if allowed
        if (not ff_path) and (OS_NAME == "Linux") and self.use_path_linux_var.get():
            ff_path = which_first(ff_names)
        if ff_path: self.ffmpeg_entry.set_text(ff_path)
        else: self.ffmpeg_entry.set_placeholder(self.ffmpeg_placeholder)

        cm_path = find_in_nested_subdir_with_bin(top, DEFAULT_DIRS["sfm"], "colmap", cm_names) or find_in_subdir_with_bin(top, DEFAULT_DIRS["sfm"], cm_names)
        if (not cm_path) and (OS_NAME == "Linux") and self.use_path_linux_var.get():
            cm_path = which_first(cm_names)
        if cm_path: self.colmap_entry.set_text(cm_path)
        else: self.colmap_entry.set_placeholder(self.colmap_placeholder)

        gm_path = find_in_nested_subdir_with_bin(top, DEFAULT_DIRS["sfm"], "glomap", gm_names) or find_in_subdir_with_bin(top, DEFAULT_DIRS["sfm"], gm_names)
        if (not gm_path) and (OS_NAME == "Linux") and self.use_path_linux_var.get():
            gm_path = which_first(gm_names)
        if gm_path: self.glomap_entry.set_text(gm_path)
        else: self.glomap_entry.set_placeholder(self.glomap_placeholder)

    def _detect_from_system_path(self):
        if OS_NAME != "Linux":
            messagebox.showinfo("Info", self.S["msg_linux_only"]); return
        found = []
        if not self.ffmpeg_entry.get_text():
            p = which_first(["ffmpeg"]); 
            if p: self.ffmpeg_entry.set_text(p); found.append(("ffmpeg", p))
        if not self.colmap_entry.get_text():
            p = which_first(["colmap"]);
            if p: self.colmap_entry.set_text(p); found.append(("COLMAP", p))
        if not self.glomap_entry.get_text():
            p = which_first(["glomap"]);
            if p: self.glomap_entry.set_text(p); found.append(("GLOMAP", p))
        if found: messagebox.showinfo("Info", self.S["msg_found"] + "\n" + "\n".join([f"{n}: {p}" for n,p in found]))
        else: messagebox.showinfo("Info", self.S["msg_found_none"])

    
    def _sync_windows_prebuilt_urls(self):
        """Update COLMAP/GLOMAP URL entries to match the CUDA checkbox (Windows only)."""
        try:
            if OS_NAME != "Windows":
                return
            want_cuda = False
            if hasattr(self, "use_cuda_build_var"):
                try:
                    want_cuda = bool(self.use_cuda_build_var.get())
                except Exception:
                    want_cuda = False
            else:
                want_cuda = detect_cuda()
            colmap_url_cuda = "https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-cuda.zip"
            colmap_url_nocuda = "https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-nocuda.zip"
            glomap_url_cuda = "https://github.com/colmap/glomap/releases/download/1.1.0/glomap-x64-windows-cuda.zip"
            glomap_url_nocuda = "https://github.com/colmap/glomap/releases/download/1.1.0/glomap-x64-windows-nocuda.zip"
            if hasattr(self, "colmap_url_var"):
                self.colmap_url_var.set(colmap_url_cuda if want_cuda else colmap_url_nocuda)
            if hasattr(self, "glomap_url_var"):
                self.glomap_url_var.set(glomap_url_cuda if want_cuda else glomap_url_nocuda)
        except Exception:
            pass

        # --- Installer-Dialog ---
        # Windows: lädt ZIPs, Linux: Source-Build, macOS: nicht automatisiert.
    def _open_installer_dialog(self):
        # Installer unterstützt Linux (Build) und Windows (Prebuilt-Downloads)
        # macOS momentan nicht automatisiert.
        win = tk.Toplevel(self); win.title(self.S["installer_title"]); win.geometry("820x600"); win.grab_set()
        frm = ttk.Frame(win); frm.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(frm, text=self.S["installer_what"]).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0,6))
        self.inst_ffmpeg = tk.BooleanVar(value=True); self.inst_colmap = tk.BooleanVar(value=False); self.inst_glomap = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text=self.S["installer_ffmpeg"], variable=self.inst_ffmpeg).grid(row=1, column=0, sticky="w")

        ttk.Checkbutton(frm, text=self.S["installer_colmap"], variable=self.inst_colmap).grid(row=2, column=0, sticky="w", pady=(8,0))
        ttk.Label(frm, text=self.S["installer_source"]).grid(row=3, column=0, sticky="e")
        self.colmap_url_var = tk.StringVar(value=("https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-cuda.zip" if OS_NAME=="Windows" else "https://github.com/colmap/colmap/archive/refs/tags/3.12.3.tar.gz"))
        ttk.Entry(frm, textvariable=self.colmap_url_var, width=70).grid(row=3, column=1, sticky="we", padx=(6,0), columnspan=3)

        ttk.Checkbutton(frm, text=self.S["installer_glomap"], variable=self.inst_glomap).grid(row=4, column=0, sticky="w", pady=(8,0))
        ttk.Label(frm, text=self.S["installer_source"]).grid(row=5, column=0, sticky="e")
        self.glomap_url_var = tk.StringVar(value=("https://github.com/colmap/glomap/releases/download/1.1.0/glomap-x64-windows-cuda.zip" if OS_NAME=="Windows" else "https://github.com/colmap/glomap/archive/refs/tags/1.1.0.tar.gz"))
        ttk.Entry(frm, textvariable=self.glomap_url_var, width=70).grid(row=5, column=1, sticky="we", padx=(6,0), columnspan=3)

        self.use_cuda_build_var = tk.BooleanVar(value=True)
        try:
            self.use_cuda_build_var.trace_add("write", lambda *a: self._sync_windows_prebuilt_urls())
        except Exception:
            pass
        self._sync_windows_prebuilt_urls()
        ttk.Checkbutton(frm, text=self.S["installer_use_cuda"], variable=self.use_cuda_build_var).grid(row=6, column=0, sticky="w", pady=(12,0))

        self.try_install_cuda_var = tk.BooleanVar(value=False)
        cb_cuda_pkg = ttk.Checkbutton(frm, text=self.S["installer_try_cuda_pkg"], variable=self.try_install_cuda_var)
        if OS_NAME == "Windows": cb_cuda_pkg.state(["disabled"])
        cb_cuda_pkg.grid(row=7, column=0, columnspan=3, sticky="w")

        frm.grid_columnconfigure(1, weight=1)
        btnbar = ttk.Frame(win); btnbar.pack(fill="x", pady=(8,0))
        ttk.Button(btnbar, text=self.S["installer_start"], command=lambda: self._run_installer(win)).pack(side="left")
        ttk.Button(btnbar, text=self.S["installer_close"], command=win.destroy).pack(side="right")
        note = ttk.Label(win, text=self.S["installer_note"], foreground="#555")
        note.pack(fill="x", padx=12, pady=8)

        # Nur unter Windows: Fortschrittsbalken im Dialog anzeigen
        if OS_NAME == "Windows":
            self.install_progress = ttk.Progressbar(win, mode="determinate")
            self.install_progress.pack(fill="x", padx=12, pady=(0, 8))

    def _log_install(self, msg):
        self.log_line("[INSTALL] " + msg)

    def _run_installer(self, win):
        if getattr(self, "install_progress", None):
            # Vor Start einmal zurücksetzen
            self.install_progress.config(value=0, maximum=0)
        threading.Thread(target=self._installer_worker, args=(win,), daemon=True).start()

    def _extras_for(self, pm, tool):
        if pm == "apt":
            if tool == "colmap":
                extras = ["libsqlite3-dev","libflann-dev","libglew-dev","libqt5svg5-dev","pkg-config",
                          "libcgal-dev","libblas-dev","liblapack-dev","libmetis-dev","gcc-12","g++-12"]
            elif tool == "glomap":
                extras = ["libsqlite3-dev","libflann-dev","libglew-dev","libfreeimage-dev","qtbase5-dev","libqt5opengl5-dev","pkg-config",
                          "libcgal-dev","libblas-dev","liblapack-dev","libmetis-dev"]
            else:
                extras = []
        elif pm == "dnf":
            extras = ["sqlite-devel","flann-devel","glew-devel","pkgconf-pkg-config","CGAL-devel","blas-devel","lapack-devel","metis-devel"]
            if tool == "glomap":
                extras += ["freeimage-devel","qt5-qtbase-devel","qt5-qtopengl-devel"]
        elif pm == "zypper":
            extras = ["sqlite3-devel","flann-devel","pkgconf-pkg-config","cgal-devel","blas-devel","lapack-devel","metis-devel"]
            if tool == "glomap":
                extras += ["freeimage-devel","libqt5-qtbase-devel","libqt5-qtopengl-devel"]
        elif pm == "pacman":
            extras = ["sqlite","flann","glew","pkgconf","cgal","blas","lapack","metis"]
            if tool == "glomap":
                extras += ["freeimage","qt5-base"]
        elif pm == "apk":
            extras = ["sqlite-dev","flann-dev","glew-dev","pkgconf","cgal-dev","blas-dev","lapack-dev","metis-dev"]
            if tool == "glomap":
                extras += ["freeimage-dev","qt5-qtbase-dev"]
        else:
            extras = []
        return extras

    def _ensure_pacman_repo_packages(self, pm, pkgs):
        # Prüft, ob freeimage/metis im offiziellen Repo verfügbar sind, bevor pacman ausgeführt wird.
        if pm != "pacman" or not pkgs:
            return True
        to_check = [name for name in ("freeimage", "metis") if name in pkgs]
        if not to_check:
            return True
        missing = []
        for name in to_check:
            try:
                res = subprocess.run(["pacman", "-Si", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as exc:
                self._log_install(f"[pacman] Repository-Prüfung für {name} fehlgeschlagen: {exc}")
                missing.append(name)
                continue
            if res.returncode != 0:
                missing.append(name)
        if missing:
            self._log_install(f"[pacman] Pakete nicht in aktivierten Repositories gefunden: {' '.join(missing)}")
            aur_helper = which_first(["yay", "paru"])  # finde verfügbaren AUR-Helper für eine mögliche Automatisierung
            if aur_helper and self._ask_aur_helper_permission(aur_helper, missing):
                helper_name = Path(aur_helper).name
                cmd = [aur_helper, "-S", "--needed", "--noconfirm", *missing]
                self._log_install(f"[pacman] Starte {helper_name} für fehlende Pakete: {' '.join(missing)}")
                aur_stdout = ""
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    aur_stdout, _ = proc.communicate("1\n" * len(missing))
                except Exception as exc:
                    self._log_install(f"[pacman] {helper_name} konnte nicht ausgeführt werden: {exc}")
                else:
                    if proc.returncode == 0:
                        self._log_install(f"[pacman] {helper_name} erfolgreich abgeschlossen.")
                        still_missing = pkg_missing("pacman", missing, self._log_install)
                        if not still_missing:
                            return True
                        self._log_install(f"[pacman] Pakete fehlen weiterhin nach {helper_name}: {' '.join(still_missing)}")
                    else:
                        self._log_install(f"[pacman] {helper_name} meldete Fehlercode {proc.returncode}.")
                        out = (aur_stdout or "").strip().splitlines()
                        for line in out[:10]:
                            self._log_install(f"[{helper_name}] {line}")
                        if len(out) > 10:
                            self._log_install(f"[{helper_name}] … {len(out) - 10} weitere Zeilen unterdrückt …")
                self._log_install("[pacman] Bitte installiere die Pakete manuell aus dem AUR (z. B. `yay -S freeimage metis`) und starte den Installer erneut.")
                self._log_install("Installer abgebrochen – pacman-Pakete fehlen.")
                return False
            if not aur_helper:
                self._log_install("[pacman] Kein unterstützter AUR-Helper (yay/paru) gefunden.")
            else:
                self._log_install("[pacman] Automatische AUR-Installation wurde abgelehnt.")
            self._log_install("[pacman] Bitte installiere die Pakete manuell aus dem AUR (z. B. `yay -S freeimage metis`) und starte den Installer erneut.")
            self._log_install("Installer abgebrochen – pacman-Pakete fehlen.")
            return False
        return True

    def _ask_aur_helper_permission(self, helper_path, pkgs):
        # Fragt threadsicher im UI-Thread nach, ob der gefundene AUR-Helper genutzt werden darf.
        decision = {"ok": False}
        evt = threading.Event()

        def _prompt():
            try:
                helper_name = Path(helper_path).name
                pkg_list = " ".join(pkgs)
                msg = (f"{helper_name} wurde gefunden. "
                       f"Darf der Installer jetzt `{helper_name} -S --needed {pkg_list}` ausführen?")
                decision["ok"] = messagebox.askyesno("AUR-Installation", msg)
            except Exception as exc:
                self._log_install(f"[pacman] Rückfrage zur AUR-Installation fehlgeschlagen: {exc}")
            finally:
                evt.set()

        try:
            self.after(0, _prompt)
            evt.wait()
        except Exception as exc:
            self._log_install(f"[pacman] Rückfrage konnte nicht angezeigt werden: {exc}")
            return False
        return decision["ok"]

    def _win_copy_tool_bin(self, extracted_root: Path, exe_name: str, target_bin: Path, log_fn, progress_cb=None):
        try:
            exe_path = None
            for p in extracted_root.rglob(exe_name):
                exe_path = p
                break
            if not exe_path:
                log_fn(f"[WIN] {exe_name} nicht im Archiv gefunden.")
                return False
            src_dir = exe_path.parent
            target_bin.mkdir(parents=True, exist_ok=True)
            items = list(src_dir.iterdir())
            total = len(items)
            for i, item in enumerate(items, 1):
                dst = target_bin / item.name
                try:
                    if item.is_dir():
                        if item.name.lower() in ("lib","share","plugins","shaders"):
                            if dst.exists():
                                shutil.rmtree(dst)
                            shutil.copytree(item, dst)
                    else:
                        shutil.copy2(item, dst)
                except Exception:
                    pass
                if progress_cb:
                    progress_cb(total, i)
            log_fn(f"[WIN] Installiert: {exe_name} → {target_bin}")
            return True
        except Exception as e:
            log_fn(f"[WIN] Kopieren fehlgeschlagen für {exe_name}: {e}")
            return False

    def _copytree_overwrite(self, src_dir, dst_dir, progress_cb=None):
        src_dir = Path(src_dir)
        dst_dir = Path(dst_dir)
        files = [p for p in src_dir.rglob('*') if p.is_file()]
        total = len(files)
        dst_dir.mkdir(parents=True, exist_ok=True)
        if progress_cb:
            progress_cb(total, 0)
        for i, f in enumerate(files, 1):
            dest = dst_dir / f.relative_to(src_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            if progress_cb:
                progress_cb(total, i)

        # --- Installer Worker ---
        # Führt Installationen im Hintergrund aus.
        # Downloads ohne sudo, Systempakete mit sudo.
    def _installer_worker(self, win):
        osr = _read_os_release() if OS_NAME == "Linux" else {}
        self._log_install(f"OS: {OS_NAME} {osr.get('NAME','')} {osr.get('VERSION','')}")
        has_cuda = detect_cuda(); self._log_install(f"CUDA erkannt: {'Ja' if has_cuda else 'Nein'}")
        pm = _detect_pkg_manager() if OS_NAME == "Linux" else None
        top = Path(self.top_dir_var.get())
        # --- Batched package installation (Linux) ---
        # Sammle alle benötigten Pakete entsprechend der Auswahl und installiere sie in EINEM Rutsch.
        if OS_NAME == "Linux":
            all_pkgs = []

            # Optional: CUDA Toolkit (nur wenn angehakt)
            if getattr(self, "try_install_cuda_var", None) and self.try_install_cuda_var.get():
                if pm == "apt":
                    all_pkgs += ["nvidia-cuda-toolkit"]
                elif pm == "dnf":
                    all_pkgs += ["cuda", "cuda-toolkit"]
                elif pm == "zypper":
                    all_pkgs += ["cuda"]
                elif pm == "pacman":
                    all_pkgs += ["cuda"]
                elif pm == "apk":
                    # Alpine: kein offizielles CUDA-Paket
                    pass

            # ffmpeg (falls ausgewählt)
            if getattr(self, "inst_ffmpeg", None) and self.inst_ffmpeg.get():
                all_pkgs += ["ffmpeg"]

            # COLMAP Build-Abhängigkeiten (falls ausgewählt)
            if getattr(self, "inst_colmap", None) and self.inst_colmap.get():
                if pm == "apt":
                    colmap_base = ["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                                   "libfreeimage-dev","libgoogle-glog-dev","libgflags-dev","qtbase5-dev","libqt5opengl5-dev","ninja-build"]
                elif pm == "dnf":
                    colmap_base = ["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                   "freeimage-devel","glog-devel","gflags-devel","qt5-qtbase-devel","qt5-qtopengl-devel","ninja-build"]
                elif pm == "zypper":
                    colmap_base = ["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                   "freeimage-devel","glog-devel","gflags-devel","libqt5-qtbase-devel","libqt5-qtopengl-devel","ninja"]
                elif pm == "pacman":
                    colmap_base = ["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","freeimage","google-glog","gflags","qt5-base","ninja"]
                elif pm == "apk":
                    colmap_base = ["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev",
                                   "freeimage-dev","glog-dev","gflags-dev","qt5-qtbase-dev","ninja"]
                else:
                    colmap_base = []
                all_pkgs += colmap_base + self._extras_for(pm, "colmap")

            # GLOMAP Build-Abhängigkeiten (falls ausgewählt)
            if getattr(self, "inst_glomap", None) and self.inst_glomap.get():
                if pm == "apt":
                    glomap_base = ["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                                   "libgoogle-glog-dev","libgflags-dev","ninja-build"]
                elif pm == "dnf":
                    glomap_base = ["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                   "glog-devel","gflags-devel","ninja-build"]
                elif pm == "zypper":
                    glomap_base = ["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                   "glog-devel","gflags-devel","ninja"]
                elif pm == "pacman":
                    glomap_base = ["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","google-glog","gflags","ninja"]
                elif pm == "apk":
                    glomap_base = ["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev","glog-dev","gflags-dev","ninja"]
                else:
                    glomap_base = []
                all_pkgs += glomap_base + self._extras_for(pm, "glomap")

            # Deduplicate, Reihenfolge bewahren
            all_pkgs = _unique_preserve_order(all_pkgs)

            if all_pkgs:
                self._log_install("Installiere Pakete gesammelt: " + " ".join(all_pkgs))
                if not self._ensure_pacman_repo_packages(pm, all_pkgs):
                    # Bei fehlenden Repo-Paketen (nur AUR) Installation abbrechen.
                    return
                pkg_install(pm, all_pkgs, self._log_install)
                self._batched_pkg_install = True
            else:
                self._log_install("Keine systemweiten Pakete erforderlich.")



        if OS_NAME == "Windows":
            success = True
            try:
                self._log_install("Windows: lade vorcompilierte Pakete…")
                has_cuda = detect_cuda()
                top = Path(self.top_dir_var.get())
                sources_dir = top / DEFAULT_DIRS["sources"]
                colmap_src = sources_dir / "colmap"
                glomap_src = sources_dir / "glomap"
                # Fortschritts-Callback für Downloads/Kopien
                def _prog(total, done):
                    try:
                        if total:
                            self.install_progress.config(maximum=total)
                        self.install_progress.config(value=done)
                        self.update_idletasks()
                    except Exception:
                        pass
                def _remote_size(u: str) -> int:
                    try:
                        from urllib.request import Request, urlopen
                        with urlopen(Request(u, method='HEAD')) as r:
                            return int(r.headers.get('Content-Length') or 0)
                    except Exception:
                        return 0
                # URLs
                colmap_url_cuda = "https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-cuda.zip"
                colmap_url_nocuda = "https://github.com/colmap/colmap/releases/download/3.12.3/colmap-x64-windows-nocuda.zip"
                glomap_url_cuda = "https://github.com/colmap/glomap/releases/download/1.1.0/glomap-x64-windows-cuda.zip"
                glomap_url_nocuda = "https://github.com/colmap/glomap/releases/download/1.1.0/glomap-x64-windows-nocuda.zip"
                ffmpeg_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                prefer_cuda = bool(getattr(self, "use_cuda_build_var", None) and self.use_cuda_build_var.get())
                want_cuda = prefer_cuda if getattr(self, "use_cuda_build_var", None) else has_cuda
                # ffmpeg
                if getattr(self, "inst_ffmpeg", None) and self.inst_ffmpeg.get():
                    self._log_install("[INSTALL] ffmpeg (Windows prebuilt)")
                    from urllib.parse import urlsplit
                    archive = sources_dir / Path(urlsplit(ffmpeg_url).path).name
                    sz = _remote_size(ffmpeg_url)
                    if sz:
                        self.install_progress.config(maximum=sz)
                    download_file(ffmpeg_url, archive, self._log_install, progress_cb=_prog)
                    self.install_progress.config(value=0)
                    self._log_install("Download abgeschlossen")
                    ff_src = extract_archive(archive, sources_dir / "ffmpeg", self._log_install)
                    if ff_src:
                        target_bin = top / DEFAULT_DIRS["ffmpeg"] / "bin"
                        self._win_copy_tool_bin(ff_src, "ffmpeg.exe", target_bin, self._log_install, progress_cb=_prog)
                        self.install_progress.config(value=0)
                        self._log_install("Install abgeschlossen")
                # COLMAP
                if getattr(self, "inst_colmap", None) and self.inst_colmap.get():
                    url = colmap_url_cuda if want_cuda else colmap_url_nocuda
                    self._log_install(f"[INSTALL] COLMAP Quellen: {url}")
                    from urllib.parse import urlsplit
                    archive = sources_dir / Path(urlsplit(url).path).name
                    sz = _remote_size(url)
                    if sz:
                        self.install_progress.config(maximum=sz)
                    download_file(url, archive, self._log_install, progress_cb=_prog)
                    self.install_progress.config(value=0)
                    self._log_install("Download abgeschlossen")
                    cm_src = extract_archive(archive, colmap_src, self._log_install)
                    if cm_src:
                        children = [p for p in (cm_src).iterdir()]
                        colmap_root = cm_src
                        if len(children) == 1 and children[0].is_dir():
                            colmap_root = children[0]
                        target_root = top / DEFAULT_DIRS["sfm"] / "colmap"
                        self._copytree_overwrite(colmap_root, target_root, progress_cb=_prog)
                        self.install_progress.config(value=0)
                        self._log_install("Install abgeschlossen")
                        self._log_install(f"[WIN] COLMAP nach {target_root} kopiert.")
                # GLOMAP
                if getattr(self, "inst_glomap", None) and self.inst_glomap.get():
                    url = glomap_url_cuda if want_cuda else glomap_url_nocuda
                    self._log_install(f"[INSTALL] GLOMAP Quellen: {url}")
                    from urllib.parse import urlsplit
                    archive = sources_dir / Path(urlsplit(url).path).name
                    sz = _remote_size(url)
                    if sz:
                        self.install_progress.config(maximum=sz)
                    download_file(url, archive, self._log_install, progress_cb=_prog)
                    self.install_progress.config(value=0)
                    self._log_install("Download abgeschlossen")
                    target_root = top / DEFAULT_DIRS["sfm"] / "glomap"
                    # Extract only 'bin/' from archive into target_root/bin
                    try:
                        import zipfile
                        shutil.rmtree(target_root / "bin", ignore_errors=True)
                        (target_root / "bin").mkdir(parents=True, exist_ok=True)
                        with zipfile.ZipFile(archive, 'r') as zf:
                            members = [n for n in zf.namelist() if n and not n.endswith('/')]
                            for i, n in enumerate(members, 1):
                                parts = [p for p in n.split('/') if p]
                                if not parts:
                                    continue
                                if parts[0].lower() == 'bin':
                                    rel = '/'.join(parts[1:])
                                elif len(parts) >= 2 and parts[1].lower() == 'bin':
                                    rel = '/'.join(parts[2:])
                                else:
                                    continue
                                if not rel:
                                    continue
                                dest = (target_root / 'bin' / rel)
                                dest.parent.mkdir(parents=True, exist_ok=True)
                                with zf.open(n) as src, open(dest, 'wb') as dst:
                                    shutil.copyfileobj(src, dst)
                                _prog(len(members), i)
                        self.install_progress.config(value=0)
                        self._log_install("Install abgeschlossen")
                        self._log_install(f"[WIN] GLOMAP bin extrahiert nach {target_root / 'bin'}")
                    except Exception as e:
                        self._log_install(f"[INSTALL] Fehler: Konnte GLOMAP bin nicht extrahieren: {e}")
                    # (wrapper cleanup skipped; we extract bin directly)
                    # move its contents up so that target_root/bin/... exists.
                    try:
                        if target_root.exists():
                            _kids = [p for p in target_root.iterdir()]
                            if len(_kids) == 1 and _kids[0].is_dir() and _kids[0].name.lower() != 'bin':
                                _wrapper = _kids[0]
                                for _item in _wrapper.iterdir():
                                    shutil.move(str(_item), str(target_root / _item.name))
                                _sh.rmtree(_wrapper, ignore_errors=True)
                                self._log_install(f"[WIN] GLOMAP Wrapper '{_wrapper.name}' entfernt – Inhalte nach {target_root} verschoben.")
                    except Exception as e:
                        self._log_install(f"[INSTALL] Warnung: Konnte Wrapper nicht bereinigen: {e}")

                    if True:
                        self._log_install(f"[WIN] GLOMAP entpackt nach {target_root}")
                    # ANGLE/Software-OpenGL DLLs sicherstellen (Windows, nach COLMAP-Entpacken)
                    try:
                        colmap_dir = base_dir / '01 GLOMAP' / 'colmap'
                        _win_ensure_angle_dlls(colmap_dir, sources_dir, self._log_install)
                    except Exception as e:
                        self._log_install(f"[INSTALL] Warnung: ANGLE-Ergänzung fehlgeschlagen: {e}")

                self._log_install("Installer-Durchlauf (Windows) beendet.")
                try:
                    self._auto_detect_tools()
                except Exception:
                    pass
            except Exception as e:
                success = False
                self._log_install(f"[INSTALL] Fehler: {e}")
            finally:
                self.after(0, lambda: self._installer_done(win, success))
            return
        # ===== Linux: batch dependency installation (single sudo prompt) =====
        if OS_NAME == "Linux":
            pm = _detect_pkg_manager()
            pkgs = set()
            # CUDA toolkit (optional)
            if getattr(self, "try_install_cuda_var", None) and self.try_install_cuda_var.get():
                if pm == "apt": pkgs.update(["nvidia-cuda-toolkit"])
                elif pm == "dnf": pkgs.update(["cuda","cuda-toolkit"])
                elif pm == "zypper": pkgs.update(["cuda"])
                elif pm == "pacman": pkgs.update(["cuda"])
            # ffmpeg
            if getattr(self, "inst_ffmpeg", None) and self.inst_ffmpeg.get():
                pkgs.update(["ffmpeg"])
            # COLMAP deps
            if getattr(self, "inst_colmap", None) and self.inst_colmap.get():
                if pm == "apt":
                    pkgs.update(["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                                 "libfreeimage-dev","libgoogle-glog-dev","libgflags-dev","qtbase5-dev","libqt5opengl5-dev","ninja-build"])
                elif pm == "dnf":
                    pkgs.update(["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "freeimage-devel","glog-devel","gflags-devel","qt5-qtbase-devel","qt5-qtopengl-devel","ninja-build"])
                elif pm == "zypper":
                    pkgs.update(["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "freeimage-devel","glog-devel","gflags-devel","libqt5-qtbase-devel","libqt5-qtopengl-devel","ninja"])
                elif pm == "pacman":
                    pkgs.update(["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","freeimage","google-glog","gflags","qt5-base","ninja"])
                elif pm == "apk":
                    pkgs.update(["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev",
                                 "freeimage-dev","glog-dev","gflags-dev","qt5-qtbase-dev","ninja"])
                pkgs.update(self._extras_for(pm, "colmap"))
            # GLOMAP deps
            if getattr(self, "inst_glomap", None) and self.inst_glomap.get():
                if pm == "apt":
                    pkgs.update(["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                                 "libgoogle-glog-dev","libgflags-dev","ninja-build"])
                elif pm == "dnf":
                    pkgs.update(["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "glog-devel","gflags-devel","ninja-build"])
                elif pm == "zypper":
                    pkgs.update(["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "glog-devel","gflags-devel","ninja"])
                elif pm == "pacman":
                    pkgs.update(["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","google-glog","gflags","ninja"])
                elif pm == "apk":
                    pkgs.update(["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev","glog-dev","gflags-dev","ninja"])
                pkgs.update(self._extras_for(pm, "glomap"))
            if pkgs and not getattr(self, "_batched_pkg_install", False):
                self._log_install("Paketabhängigkeiten gesammelt – einmaliger Paketmanager-Lauf …")
                if not self._ensure_pacman_repo_packages(pm, pkgs):
                    return
                pkg_install(pm, sorted(pkgs), self._log_install)
                self._batched_pkg_install = True
            else:
                self._batched_pkg_install = False
        # ===== end batch =====




        # ===== Linux: Paketinstallation in einem Durchlauf (ein Passwort-Prompt) =====
        self._batched_pkg_install = True
        pm = _detect_pkg_manager() if OS_NAME == "Linux" else None
        top = Path(self.top_dir_var.get())
        pkgs = set()
        if pm:
            # Optional: CUDA Toolkit
            if getattr(self, "try_install_cuda_var", None) and self.try_install_cuda_var.get():
                if pm == "apt":
                    pkgs.update(["nvidia-cuda-toolkit"])
                elif pm == "dnf":
                    pkgs.update(["cuda", "cuda-toolkit"])
                elif pm == "zypper":
                    pkgs.update(["cuda"])
                elif pm == "pacman":
                    pkgs.update(["cuda"])
            # ffmpeg
            if getattr(self, "inst_ffmpeg", None) and self.inst_ffmpeg.get():
                pkgs.update(["ffmpeg"])
            # COLMAP deps
            if getattr(self, "inst_colmap", None) and self.inst_colmap.get():
                if pm == "apt":
                    pkgs.update(["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                                 "libfreeimage-dev","libgoogle-glog-dev","libgflags-dev","qtbase5-dev","libqt5opengl5-dev","ninja-build",
                                 "libsqlite3-dev","libflann-dev","libglew-dev","libqt5svg5-dev","pkg-config",
                                 "libcgal-dev","libblas-dev","liblapack-dev","libmetis-dev","gcc-12","g++-12"])
                elif pm == "dnf":
                    pkgs.update(["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "freeimage-devel","glog-devel","gflags-devel","qt5-qtbase-devel","qt5-qtopengl-devel","ninja-build",
                                 "sqlite-devel","flann-devel","glew-devel","pkgconf-pkg-config","CGAL-devel","blas-devel","lapack-devel","metis-devel"])
                elif pm == "zypper":
                    pkgs.update(["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "freeimage-devel","glog-devel","gflags-devel","libqt5-qtbase-devel","libqt5-qtopengl-devel","ninja",
                                 "sqlite3-devel","flann-devel","glew-devel","pkgconf-pkg-config","cgal-devel","blas-devel","lapack-devel","metis-devel"])
                elif pm == "pacman":
                    pkgs.update(["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","freeimage","google-glog","gflags","qt5-base","ninja",
                                 "sqlite","flann","glew","pkgconf","cgal","blas","lapack","metis"])
                elif pm == "apk":
                    pkgs.update(["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev",
                                 "freeimage-dev","glog-dev","gflags-dev","qt5-qtbase-dev","ninja",
                                 "sqlite-dev","flann-dev","glew-dev","pkgconf","cgal-dev","blas-dev","lapack-dev","metis-dev"])
            # GLOMAP deps
            if getattr(self, "inst_glomap", None) and self.inst_glomap.get():
                if pm == "apt":
                    pkgs.update(["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                                 "libgoogle-glog-dev","libgflags-dev","ninja-build",
                                 "libsqlite3-dev","flann-dev","glew-dev","freeimage-dev","pkg-config"])
                elif pm == "dnf":
                    pkgs.update(["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "glog-devel","gflags-devel","ninja-build",
                                 "sqlite-devel","flann-devel","glew-devel","pkgconf-pkg-config","freeimage-devel"])
                elif pm == "zypper":
                    pkgs.update(["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                                 "glog-devel","gflags-devel","ninja",
                                 "sqlite3-devel","flann-devel","glew-devel","pkgconf-pkg-config","freeimage-devel"])
                elif pm == "pacman":
                    pkgs.update(["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","google-glog","gflags","ninja",
                                 "sqlite","flann","glew","freeimage"])
                elif pm == "apk":
                    pkgs.update(["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev","glog-dev","gflags-dev","ninja",
                                 "sqlite-dev","flann-dev","glew-dev","freeimage-dev"])
        if pkgs and not getattr(self, "_batched_pkg_install", False):
            self._log_install("Paketabhängigkeiten gesammelt – führe Paketmanager einmalig aus …")
            if not self._ensure_pacman_repo_packages(pm, pkgs):
                return
            pkg_install(pm, sorted(pkgs), self._log_install)
        # ===== Ende Batch-Install =====
        if getattr(self, "try_install_cuda_var", None) and self.try_install_cuda_var.get():
            cuda_pkgs = []
            if pm == "apt": cuda_pkgs = ["nvidia-cuda-toolkit"]
            elif pm == "dnf": cuda_pkgs = ["cuda", "cuda-toolkit"]
            elif pm == "zypper": cuda_pkgs = ["cuda"]
            elif pm == "pacman": cuda_pkgs = ["cuda"]
            if cuda_pkgs:
                self._log_install(f"Versuche CUDA Toolkit zu installieren: {' '.join(cuda_pkgs)}")
                if not getattr(self, "_batched_pkg_install", False):
                    if not self._ensure_pacman_repo_packages(pm, cuda_pkgs):
                        return
                    pkg_install(pm, cuda_pkgs, self._log_install)

        if getattr(self, "inst_ffmpeg", None) and self.inst_ffmpeg.get():
            self._log_install("ffmpeg Installation über Paketmanager…")
            code = 0
            if not getattr(self, "_batched_pkg_install", False):
                if not self._ensure_pacman_repo_packages(pm, ["ffmpeg"]):
                    return
                code = pkg_install(pm, ["ffmpeg"], self._log_install)
            if code == 0:
                path = which_first(["ffmpeg"]); self._log_install(f"ffmpeg installiert. Pfad: {path or 'nicht im PATH gefunden'}")
                if path: self.ffmpeg_entry.set_text(path)
            else: self._log_install("ffmpeg Installation fehlgeschlagen.")

        if getattr(self, "inst_colmap", None) and self.inst_colmap.get():
            self._log_install("COLMAP Abhängigkeiten installieren…")
            if pm == "apt":
                base = ["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                        "libfreeimage-dev","libgoogle-glog-dev","libgflags-dev","qtbase5-dev","libqt5opengl5-dev","ninja-build"]
            elif pm == "dnf":
                base = ["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                        "freeimage-devel","glog-devel","gflags-devel","qt5-qtbase-devel","qt5-qtopengl-devel","ninja-build"]
            elif pm == "zypper":
                base = ["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                        "freeimage-devel","glog-devel","gflags-devel","libqt5-qtbase-devel","libqt5-qtopengl-devel","ninja"]
            elif pm == "pacman":
                base = ["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","freeimage","google-glog","gflags","qt5-base","ninja"]
            elif pm == "apk":
                base = ["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev",
                        "freeimage-dev","glog-dev","gflags-dev","qt5-qtbase-dev","ninja"]
            else:
                base = []
            if base and not getattr(self, "_batched_pkg_install", False):
                if not self._ensure_pacman_repo_packages(pm, base):
                    return
                pkg_install(pm, base, self._log_install)
            colmap_url = self.colmap_url_var.get().strip() if hasattr(self, "colmap_url_var") else ""
            if not colmap_url:
                self._log_install("COLMAP Quelle nicht gesetzt – überspringe Build.")
            else:
                src_dir = top / DEFAULT_DIRS["sources"] / "colmap"
                self._log_install(f"COLMAP Quelle: {colmap_url}")
                if src_dir.exists(): shutil.rmtree(src_dir, ignore_errors=True)
                src = ensure_source_from_url(colmap_url, src_dir, self._log_install)
                if not src or not Path(src).exists():
                    self._log_install("Quellen konnten nicht vorbereitet werden – COLMAP.")
                else:
                    build_dir = src_dir / "build"
                    install_prefix = top / DEFAULT_DIRS["sfm"] / "colmap"
                    cuda_args = _maybe_cuda_host_flag(pm, self._log_install) if self.use_cuda_build_var.get() else ["-DCUDA_ENABLED=OFF"]
                    if "-DCUDA_ENABLED=ON" in cuda_args:
                        self._log_install("COLMAP: versuche CUDA-Build…")
                    elif "-DCUDA_ENABLED=OFF" in cuda_args:
                        self._log_install("COLMAP: CUDA deaktiviert (Konfigurationswahl/Heuristik).")
                    extra_args = [f"-DCMAKE_INSTALL_PREFIX={install_prefix}", "-DBLA_VENDOR=Intel10_64lp"] + cuda_args
                    code = cmake_configure_ninja(src_dir, build_dir, self._log_install, extra_args=extra_args)
                    if code != 0 and ("-DCUDA_ENABLED=ON" in cuda_args):
                        self._log_install("Configure mit CUDA fehlgeschlagen – Fallback ohne -DBLA_VENDOR und ohne CUDA…")
                        extra_args = [f"-DCMAKE_INSTALL_PREFIX={install_prefix}", "-DCUDA_ENABLED=OFF"]
                        code = cmake_configure_ninja(src_dir, build_dir, self._log_install, extra_args=extra_args)
                    if code != 0:
                        self._log_install("Configure ohne CUDA, zusätzlicher Fallback ohne -DBLA_VENDOR…")
                        extra_args = [f"-DCMAKE_INSTALL_PREFIX={install_prefix}"]
                        code = cmake_configure_ninja(src_dir, build_dir, self._log_install, extra_args=extra_args)
                    if code == 0:
                        code = ninja_build(build_dir, self._log_install)
                        if code == 0:
                            code = ninja_install(build_dir, self._log_install)
                            bin_expected = install_prefix / "bin" / "colmap"
                            if code == 0 and ensure_binary_installed(bin_expected, build_dir, "colmap", self._log_install):
                                self.colmap_entry.set_text(str(bin_expected.resolve())); self._log_install(f"COLMAP installiert nach: {install_prefix}")
                            elif code == 0:
                                self._log_install("`ninja install` erledigt, aber COLMAP-Binary nicht gefunden – siehe Log.")
                        else:
                            self._log_install("`ninja` Build fehlgeschlagen (COLMAP).")
                    else:
                        self._log_install("CMake Configure für COLMAP fehlgeschlagen.")

        if getattr(self, "inst_glomap", None) and self.inst_glomap.get():
            self._log_install("GLOMAP Abhängigkeiten installieren…")
            if pm == "apt":
                base = ["build-essential","cmake","git","libboost-all-dev","libeigen3-dev","libsuitesparse-dev","libceres-dev",
                        "libgoogle-glog-dev","libgflags-dev","ninja-build"]
            elif pm == "dnf":
                base = ["gcc-c++","cmake","git","boost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                        "glog-devel","gflags-devel","ninja-build"]
            elif pm == "zypper":
                base = ["gcc-c++","cmake","git","libboost-devel","eigen3-devel","suitesparse-devel","ceres-solver-devel",
                        "glog-devel","gflags-devel","ninja"]
            elif pm == "pacman":
                base = ["base-devel","cmake","git","boost","eigen","suitesparse","ceres-solver","google-glog","gflags","ninja"]
            elif pm == "apk":
                base = ["build-base","cmake","git","boost-dev","eigen-dev","suitesparse-dev","ceres-dev","glog-dev","gflags-dev","ninja"]
            else:
                base = []
            if base and not getattr(self, "_batched_pkg_install", False):
                if not self._ensure_pacman_repo_packages(pm, base):
                    return
                pkg_install(pm, base, self._log_install)
            glomap_url = self.glomap_url_var.get().strip() if hasattr(self, "glomap_url_var") else ""
            if not glomap_url:
                self._log_install("GLOMAP Quelle nicht gesetzt – überspringe Build.")
            else:
                src_dir = top / DEFAULT_DIRS["sources"] / "glomap"
                self._log_install(f"GLOMAP Quelle: {glomap_url}")
                if src_dir.exists(): shutil.rmtree(src_dir, ignore_errors=True)
                src = ensure_source_from_url(glomap_url, src_dir, self._log_install)
                if not src or not Path(src).exists():
                    self._log_install("Quellen konnten nicht vorbereitet werden – GLOMAP.")
                else:
                    build_dir = src_dir / "build"
                    install_prefix = top / DEFAULT_DIRS["sfm"] / "glomap"
                    extra_args = [f"-DCMAKE_INSTALL_PREFIX={install_prefix}"]
                    code = cmake_configure_ninja(src_dir, build_dir, self._log_install, extra_args=extra_args)
                    if code == 0:
                        code = ninja_build(build_dir, self._log_install)
                        if code == 0:
                            code = ninja_install(build_dir, self._log_install)
                            bin_expected = install_prefix / "bin" / "glomap"
                            if code == 0 and ensure_binary_installed(bin_expected, build_dir, "glomap", self._log_install):
                                self.glomap_entry.set_text(str(bin_expected.resolve())); self._log_install(f"GLOMAP installiert nach: {install_prefix}")
                            elif code == 0:
                                self._log_install("`ninja install` erledigt, aber GLOMAP-Binary nicht gefunden – siehe Log.")
                        else:
                            self._log_install("`ninja` Build fehlgeschlagen (GLOMAP).")
                    else:
                        self._log_install("CMake Configure für GLOMAP fehlgeschlagen.")

        self._log_install("Installer-Durchlauf beendet."); self._auto_detect_tools()

    def _installer_done(self, win, success):
        win.destroy()
        if success:
            tk.messagebox.showinfo("Info", self.S["installer_done_ok"])
        else:
            tk.messagebox.showerror("Fehler", self.S["installer_done_fail"])

    def test_tools(self):
        self.log.delete("1.0", "end"); self.log_line(self.S["tools_test_begin"])
        osr = _read_os_release() if OS_NAME == "Linux" else {}; self.log_line(f"[System] OS erkannt: {OS_NAME} {osr.get('NAME','')} {osr.get('VERSION','')}")
        ffmpeg = self.ffmpeg_entry.get_text()
        if ffmpeg:
            self.log_line(f"[ffmpeg] Pfad: {ffmpeg}")
            code, out = run_and_capture([ffmpeg, "-version"]); self.log_line(f"[ffmpeg] exit={code}")
            if out:
                for line in out.splitlines()[:10]: self.log_line("  " + line)
        else: self.log_line("[ffmpeg] nicht gesetzt – bitte auswählen.")

        colmap = self.colmap_entry.get_text()
        if colmap:
            self.log_line(f"[COLMAP] Pfad: {colmap}")
            code, out = run_and_capture([colmap, "-h"]); self.log_line(f"[COLMAP] exit={code}")
            if out:
                for line in out.splitlines()[:10]: self.log_line("  " + line)
            code_fx, out_fx = run_and_capture([colmap, "feature_extractor", "-h"])
            code_sm, out_sm = run_and_capture([colmap, "sequential_matcher", "-h"])
            fx_gpu = "--SiftExtraction.use_gpu" in out_fx if out_fx else False
            sm_gpu = "--SiftMatching.use_gpu" in out_sm if out_sm else False
            self.log_line(f"[COLMAP] GPU-Optionen: feature_extractor use_gpu={'Ja' if fx_gpu else 'Nein'}, sequential_matcher use_gpu={'Ja' if sm_gpu else 'Nein'}")
        else: self.log_line("[COLMAP] nicht gesetzt – bitte auswählen.")

        glomap = self.glomap_entry.get_text()
        if glomap:
            self.log_line(f"[GLOMAP] Pfad: {glomap}")
            code, out = run_and_capture([glomap, "--help"]); self.log_line(f"[GLOMAP] exit={code}")
            if out:
                for line in out.splitlines()[:10]: self.log_line("  " + line)
        else: self.log_line("[GLOMAP] nicht gesetzt (optional).")

        self.log_line(self.S["tools_test_end"])

    def load_existing_videos(self):
        # scan project video directory and add found files once
        vids_dir = Path(self.top_dir_var.get()) / DEFAULT_DIRS["videos"]
        scenes_dir = Path(self.top_dir_var.get()) / DEFAULT_DIRS["scenes"]
        exts = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".mpg", ".mpeg"}
        if vids_dir.exists():
            existing = set(self.video_list.get(0, "end"))
            for f in vids_dir.iterdir():
                if f.is_file() and f.suffix.lower() in exts:
                    if (scenes_dir / f.stem).exists():
                        continue  # skip videos with an existing scene directory
                    p = str(f)
                    if p not in existing:
                        self.video_list.insert("end", p)
                        existing.add(p)

    # ---- Video UI ----
    def add_videos(self):
        files = filedialog.askopenfilenames(title=self.S["dlg_pick_videos"],
            filetypes=[("Video","*.mp4 *.MP4 *.mov *.MOV *.avi *.AVI *.mkv *.MKV *.m4v *.M4V *.wmv *.WMV *.mpg *.MPG *.mpeg *.MPEG"), ("All files","*.*")])
        for f in files: self.video_list.insert("end", f)

    def remove_selected(self):
        for idx in reversed(self.video_list.curselection()): self.video_list.delete(idx)

    def clear_videos(self):
        self.video_list.delete(0, "end")

    # ---- Laufzeit-Anzeige ----
    def _start_elapsed(self):
        self._elapsed_start = time.time(); self.elapsed_var.set(f"{self.elapsed_prefix}: 00:00:00")
        if self._elapsed_job is None: self._elapsed_job = self.after(500, self._tick_elapsed)

    def _tick_elapsed(self):
        if self._elapsed_start is None: self._elapsed_job = None; return
        secs = int(time.time() - self._elapsed_start); h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        self.elapsed_var.set(f"{self.elapsed_prefix}: {h:02d}:{m:02d}:{s:02d}"); self._elapsed_job = self.after(500, self._tick_elapsed)

    def _stop_elapsed(self):
        if self._elapsed_job is not None:
            try: self.after_cancel(self._elapsed_job)
            except Exception: pass
            self._elapsed_job = None

    # ---- Pipeline ----
    def start_run(self):
        if getattr(self, "_worker", None) and self._worker.is_alive():
            messagebox.showinfo("Info", self.S["warn_running"]); return
        videos = list(self.video_list.get(0, "end"))
        if not videos: messagebox.showwarning("Warnung", self.S["warn_no_videos"]); return
        ffmpeg = self.ffmpeg_entry.get_text(); colmap = self.colmap_entry.get_text(); glomap = self.glomap_entry.get_text()
        if not ffmpeg or not Path(ffmpeg).exists():
            messagebox.showerror("Fehler", self.S["err_ffmpeg"]); return
        if not colmap or not Path(colmap).exists():
            messagebox.showerror("Fehler", self.S["err_colmap"]); return
        self._stop_flag = False; self.run_btn.config(state="disabled")
        self.progress.config(value=0, maximum=len(videos)); self.log.delete("1.0", "end"); self._start_elapsed()
        self._worker = threading.Thread(target=self._run_pipeline, args=(videos, ffmpeg, colmap, glomap), daemon=True); self._worker.start()

    def log_line(self, text):
        self.log.insert("end", text + "\n"); self.log.see("end"); self.update_idletasks()

    def _build_scale_filter(self):
        mode = self.res_mode.get(); w = self.width_var.get().strip(); h = self.height_var.get().strip()
        if mode == "keep": return None
        if mode == "w" and w.isdigit(): return f"scale={w}:-2"
        if mode == "h" and h.isdigit(): return f"scale=-2:{h}"
        if mode == "wh" and w.isdigit() and h.isdigit(): return f"scale={w}:{h}"
        return None

    def _build_sampling_filters(self):
        filters = []; mode = self.fps_mode.get()
        if mode == "every":
            try: n = max(1, int(self.every_n_var.get().strip()))
            except ValueError: n = 2
            if n > 1: filters.append(f"select=not(mod(n\\,{n}))")
        return filters if filters else None

    # --- ffmpeg Frame-Extraktion ---
    # Erstellt Filterkette (FPS, Skalierung), speichert JPEG Frames.
    def _ffmpeg_extract(self, ffmpeg, video_path, img_dir):
        q = self.jpeg_q_var.get().strip() or "2"
        scale_f = self._build_scale_filter(); samp_filters = self._build_sampling_filters()
        vf_chain = []; 
        if samp_filters: vf_chain.extend(samp_filters)
        if scale_f: vf_chain.append(scale_f)
        vf_arg = ",".join(vf_chain) if vf_chain else None
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "info", "-nostdin", "-i", video_path, "-qscale:v", q]
        if vf_arg: cmd.extend(["-vf", vf_arg, "-vsync", "vfr"])
        out_pattern = str(Path(img_dir) / "frame_%06d.jpg"); cmd.append(out_pattern)
        self.log_line(" ".join(shlex.quote(c) for c in cmd))
        return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_feature_extractor(self, colmap, db_path, img_dir, max_img_size, use_gpu: bool):
        cmd = [colmap, "feature_extractor", "--database_path", db_path, "--image_path", img_dir,
               "--ImageReader.single_camera", "1", "--SiftExtraction.max_image_size", str(max_img_size)]
        if use_gpu:
            cmd += ["--SiftExtraction.use_gpu", "1"]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_sequential_matcher(self, colmap, db_path, overlap, use_gpu: bool):
        cmd = [colmap, "sequential_matcher", "--database_path", db_path, "--SequentialMatching.overlap", str(overlap),
               "--SiftMatching.use_gpu", "1" if use_gpu else "0"]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _glomap_mapper(self, glomap, db_path, img_dir, sparse_dir):
        cmd = [glomap, "mapper", "--database_path", db_path, "--image_path", img_dir, "--output_path", sparse_dir]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_mapper(self, colmap, db_path, img_dir, sparse_dir):
        cmd = [colmap, "mapper", "--database_path", db_path, "--image_path", img_dir, "--output_path", sparse_dir]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_model_converter(self, colmap, in_path, out_path):
        cmd = [colmap, "model_converter", "--input_path", in_path, "--output_path", out_path, "--output_type", "TXT"]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_image_undistorter(self, colmap, img_dir, sparse_dir, dense_dir):
        cmd = [colmap, "image_undistorter", "--image_path", img_dir,
               "--input_path", f"{sparse_dir}/0", "--output_path", dense_dir]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_patch_match_stereo(self, colmap, dense_dir):
        cmd = [colmap, "patch_match_stereo", "--workspace_path", dense_dir,
               "--workspace_format", "COLMAP"]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_stereo_fusion(self, colmap, dense_dir):
        cmd = [colmap, "stereo_fusion", "--workspace_path", dense_dir,
               "--workspace_format", "COLMAP", "--output_path", f"{dense_dir}/fused.ply"]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _colmap_poisson_mesher(self, colmap, dense_dir):
        cmd = [colmap, "poisson_mesher", "--input_path", f"{dense_dir}/fused.ply",
               "--output_path", f"{dense_dir}/meshed.ply"]
        self.log_line(" ".join(shlex.quote(c) for c in cmd)); return run_cmd(cmd, log_fn=self.log_line)

    def _run_pipeline(self, videos, ffmpeg, colmap, glomap):
        try:
            scenes_dir = Path(self.scenes_dir_var.get()); scenes_dir.mkdir(parents=True, exist_ok=True)
            overlap = int(self.seq_overlap_var.get().strip() or "15"); max_img = int(self.sift_max_img_var.get().strip() or "4096")
            use_gpu = bool(self.use_gpu_var.get()); do_mesh = bool(self.mesh_var.get())
            steps_total = 8 if do_mesh else 4
            for i, video in enumerate(videos, start=1):
                if self._stop_flag: break
                vpath = Path(video); base = vpath.stem
                self.log_line(f"\n=== Verarbeite ({i}/{len(videos)}): {base} ===")
                scene_dir = scenes_dir / base; img_dir = scene_dir / "images"; sparse_dir = scene_dir / "sparse"; db_path = scene_dir / "database.db"
                img_dir.mkdir(parents=True, exist_ok=True); sparse_dir.mkdir(parents=True, exist_ok=True)
                step = 1
                self.log_line(f"[{step}/{steps_total}] {self.S['run_extract']}"); step += 1
                code = self._ffmpeg_extract(ffmpeg, str(vpath), str(img_dir))
                if code != 0:
                    self.log_line(f"[ERROR] ffmpeg fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                if not any(p.suffix.lower() == ".jpg" for p in img_dir.glob("*.jpg")):
                    self.log_line(f"[ERROR] Keine Frames extrahiert für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                self.log_line(f"[{step}/{steps_total}] {self.S['run_feat']}"); step += 1
                code = self._colmap_feature_extractor(colmap, str(db_path), str(img_dir), max_img, use_gpu)
                if code != 0:
                    self.log_line(f"[ERROR] feature_extractor fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                self.log_line(f"[{step}/{steps_total}] {self.S['run_match']}"); step += 1
                code = self._colmap_sequential_matcher(colmap, str(db_path), overlap, use_gpu)
                if code != 0:
                    self.log_line(f"[ERROR] sequential_matcher fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                self.log_line(f"[{step}/{steps_total}] {self.S['run_mapper']}"); step += 1
                use_glomap = bool(glomap) and Path(glomap).exists()
                code = self._glomap_mapper(glomap, str(db_path), str(img_dir), str(sparse_dir)) if use_glomap \
                       else self._colmap_mapper(colmap, str(db_path), str(img_dir), str(sparse_dir))
                if code != 0:
                    self.log_line(f"[ERROR] mapper fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                if do_mesh:
                    dense_dir = scene_dir / "dense"
                    dense_dir.mkdir(parents=True, exist_ok=True)
                    self.log_line(f"[{step}/{steps_total}] {self.S['run_undistort']}"); step += 1
                    code = self._colmap_image_undistorter(colmap, str(img_dir), str(sparse_dir), str(dense_dir))
                    if code != 0:
                        self.log_line(f"[ERROR] image_undistorter fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                    self.log_line(f"[{step}/{steps_total}] {self.S['run_patchmatch']}"); step += 1
                    code = self._colmap_patch_match_stereo(colmap, str(dense_dir))
                    if code != 0:
                        self.log_line(f"[ERROR] patch_match_stereo fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                    self.log_line(f"[{step}/{steps_total}] {self.S['run_fuse']}"); step += 1
                    code = self._colmap_stereo_fusion(colmap, str(dense_dir))
                    if code != 0:
                        self.log_line(f"[ERROR] stereo_fusion fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                    self.log_line(f"[{step}/{steps_total}] {self.S['run_mesher']}"); step += 1
                    code = self._colmap_poisson_mesher(colmap, str(dense_dir))
                    if code != 0:
                        self.log_line(f"[ERROR] poisson_mesher fehlgeschlagen für {base}. Überspringe."); self._advance_progress(i, len(videos)); continue
                sub0 = sparse_dir / "0"
                if sub0.exists():
                    self._colmap_model_converter(colmap, str(sub0), str(sub0)); self._colmap_model_converter(colmap, str(sub0), str(sparse_dir))
                self.log_line(f"✓ Fertig: {base}  ({i}/{len(videos)})"); self._advance_progress(i, len(videos))
            self.log_line("\\n" + self.S["done_all"])
        except Exception as e:
            self.log_line(f"[FATAL] {e}")
        finally:
            try: self.after(0, self._stop_elapsed); self.after(0, lambda: self.run_btn.config(state="normal"))
            except Exception: self.run_btn.config(state="normal")

    def _advance_progress(self, i, total):
        self.progress.config(maximum=total, value=i); self.update_idletasks()

    def _open_about_dialog(self):
        url = "https://gist.github.com/polyfjord/fc22f22770cd4dd365bb90db67a4f2dc"
        win = tk.Toplevel(self); win.title(self.S["about_title"]); win.resizable(False, False)
        frm = ttk.Frame(win); frm.pack(fill="both", expand=True, padx=12, pady=12)
        txt = tk.Text(frm, width=48, height=3, wrap="word", borderwidth=0)
        txt.pack(fill="both", expand=True)
        txt.insert("end", self.S["about_text"])
        start_idx = txt.index("end-1c")
        txt.insert("end", self.S["about_link"])
        end_idx = txt.index("end-1c")
        txt.tag_add("link", start_idx, end_idx); txt.tag_config("link", foreground="#0b61a4", underline=1)
        txt.tag_bind("link", "<Button-1>", lambda e: webbrowser.open_new_tab(url)); txt.configure(state="disabled")
        btnbar = ttk.Frame(frm); btnbar.pack(fill="x", pady=(8,0))
        donate_url = "https://paypal.me/DanielBAdberg"
        ttk.Button(btnbar, text=self.S["about_paypal_btn"], command=lambda: webbrowser.open_new_tab(donate_url)).pack(side="left")
        pat_url = "https://www.patreon.com/polyfjord"
        ttk.Button(btnbar, text="Polyfjords Patreon", command=lambda: webbrowser.open_new_tab(pat_url)).pack(side="left")
        ttk.Button(btnbar, text=self.S.get("installer_close", "Schließen"), command=win.destroy).pack(side="right")
        try:
            self.update_idletasks(); x = self.winfo_x() + self.winfo_width() - win.winfo_reqwidth() - 40; y = self.winfo_y() + 60; win.geometry(f"+{x}+{y}")
        except Exception:
            pass

if __name__ == "__main__":
    ensure_vc_redist()
    app = AutoTrackerGUI(); app.mainloop()
