# launcher.py - elHydro Server Launcher
# Konfiguriert und startet den FastAPI-Webserver mit optionalem mDNS und System Tray.

import os
import sys
import json
import shutil
import socket
import threading
import webbrowser
import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import uvicorn

from src.core.brain import soil_threshold
from src.utils.constants import (
    DEFAULT_PRESETS, TARGET_SOIL_MIN, TARGET_SOIL_MAX, IRR_DELTA_MIN, IRR_DELTA_MAX,
    write_json_atomic,
)

IS_WINDOWS = sys.platform == "win32"

# --- Optionale Abhängigkeiten ---

HAS_QR = False
try:
    import qrcode
    from PIL import Image as PilImage, ImageTk
    HAS_QR = True
except ImportError:
    pass

HAS_TRAY = False
try:
    import pystray
    from PIL import Image as PilImage, ImageTk
    HAS_TRAY = True
except ImportError:
    pass

HAS_ZEROCONF = False
try:
    from zeroconf import Zeroconf, ServiceInfo, NonUniqueNameException
    HAS_ZEROCONF = True
except ImportError:
    pass

# --- Konstanten ---

# PyInstaller entpackt Dateien in einen temporären Ordner (sys._MEIPASS).
# SCRIPT_DIR zeigt auf die mitgelieferten Dateien (static, data).
# APP_DIR zeigt auf den Ordner der .exe (für Laufzeit-Dateien).
if getattr(sys, "frozen", False):
    SCRIPT_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = SCRIPT_DIR
STATIC_DIR = os.path.join(SCRIPT_DIR, "static")
ICON_PATH = os.path.join(STATIC_DIR, "elhydro.ico")
HAS_EPAPER_SIM = False
try:
    from tools.epaper_simulator import start_embedded as epaper_start_embedded
    HAS_EPAPER_SIM = True
except ImportError:
    pass
if IS_WINDOWS:
    APPDATA_DIR = os.path.join(
        os.environ.get("USERPROFILE") or os.path.expanduser("~"), "elHydro",
    )
else:
    _xdg_data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    APPDATA_DIR = os.path.join(_xdg_data, "elHydro")
CONFIG_FILE = os.path.join(APPDATA_DIR, "config", "config.json")
MUTEX_NAME = "elHydro_Launcher_Mutex"
# Startargument im Autostart-Eintrag: Server direkt starten, Fenster im Hintergrund
AUTOSTART_ARG = "--autostart"

DEFAULT_CONFIG = {
    "port": 8000,
    "data_dir": APPDATA_DIR,
    "mdns_enabled": False,
    "mdns_mode": "hostname",       # "hostname" oder "custom"
    "mdns_custom_name": "elhydro",
    "minimize_to_tray": True,
    "autostart": False,
}

LOG_FILE = os.path.join(APPDATA_DIR, "launcher.log")

log = logging.getLogger("launcher")


def _setup_logging():
    """Loggt in launcher.log und, falls vorhanden, auf die Konsole (die exe hat keine)."""
    handlers = []
    if sys.stderr:
        handlers.append(logging.StreamHandler())
    try:
        os.makedirs(APPDATA_DIR, exist_ok=True)
        handlers.append(RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=handlers or None,
    )


_setup_logging()


# ============================================================
# Hilfsfunktionen
# ============================================================

def ensure_single_instance():
    """Verhindert Mehrfachstart. Gibt ein Handle zurück das gehalten werden muss,
    oder beendet das Programm."""
    if IS_WINDOWS:
        import ctypes
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            messagebox.showerror("elHydro", "elHydro Launcher läuft bereits.")
            sys.exit(1)
        return mutex

    import fcntl
    os.makedirs(APPDATA_DIR, exist_ok=True)
    lock_path = os.path.join(APPDATA_DIR, "launcher.lock")
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        messagebox.showerror("elHydro", "elHydro Launcher läuft bereits.")
        sys.exit(1)
    return lock_file


def load_config() -> dict:
    """Lädt die Konfiguration aus dem plattformspezifischen App-Data-Ordner."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULT_CONFIG, **saved}
        except (json.JSONDecodeError, IOError):
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    """Speichert die Konfiguration atomar in den plattformspezifischen App-Data-Ordner."""
    write_json_atomic(CONFIG_FILE, cfg, indent=2)


def get_local_ip() -> str:
    """Ermittelt die lokale IP-Adresse über einen UDP-Socket-Trick."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def port_available(port: int) -> bool:
    """Prüft ob der angegebene Port frei ist."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("0.0.0.0", port))
        s.close()
        return True
    except OSError:
        return False


def set_autostart(enable: bool):
    """Setzt oder entfernt den Autostart-Eintrag."""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            if enable:
                if getattr(sys, "frozen", False):
                    path = f'"{sys.executable}" {AUTOSTART_ARG}'
                else:
                    path = f'"{sys.executable}" "{os.path.abspath(__file__)}" {AUTOSTART_ARG}'
                winreg.SetValueEx(key, "elHydro", 0, winreg.REG_SZ, path)
            else:
                try:
                    winreg.DeleteValue(key, "elHydro")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except OSError as e:
            log.warning(f"Autostart-Registry konnte nicht geändert werden: {e}")
        return

    autostart_dir = os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "autostart",
    )
    desktop_file = os.path.join(autostart_dir, "elHydro.desktop")
    try:
        if enable:
            os.makedirs(autostart_dir, exist_ok=True)
            if getattr(sys, "frozen", False):
                exec_cmd = f'"{sys.executable}" {AUTOSTART_ARG}'
            else:
                exec_cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}" {AUTOSTART_ARG}'
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=elHydro\n"
                f"Exec={exec_cmd}\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write(content)
        elif os.path.exists(desktop_file):
            os.remove(desktop_file)
    except OSError as e:
        log.warning(f"Autostart-Datei konnte nicht geändert werden: {e}")


def create_qr_image(url: str, size: int = 220):
    """Erzeugt ein QR-Code-Bild als ImageTk.PhotoImage."""
    if not HAS_QR:
        return None
    qr = qrcode.QRCode(version=1, box_size=8, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    image = image.resize((size, size), PilImage.NEAREST)
    return ImageTk.PhotoImage(image)


def move_data(old_path: str, new_path: str) -> bool:
    """Verschiebt bestehende Daten vom alten ins neue Verzeichnis.
    Gibt True zurück wenn erfolgreich oder keine Daten vorhanden."""
    # Prüfen ob im alten Verzeichnis überhaupt Daten liegen
    files = ["device_settings.json", "plant_presets.json", "logs.jsonl"]
    folders = ["measurements"]
    has_data = any(
        os.path.exists(os.path.join(old_path, d)) for d in files + folders
    )
    if not has_data:
        return True

    os.makedirs(new_path, exist_ok=True)
    try:
        for file_name in files:
            source = os.path.join(old_path, file_name)
            if os.path.exists(source):
                shutil.move(source, os.path.join(new_path, file_name))
        for folder_name in folders:
            source = os.path.join(old_path, folder_name)
            destination = os.path.join(new_path, folder_name)
            if os.path.exists(source):
                if os.path.exists(destination):
                    # Einzelne Dateien verschieben wenn Zielordner existiert
                    for f in os.listdir(source):
                        shutil.move(os.path.join(source, f), os.path.join(destination, f))
                    if not os.listdir(source):
                        os.rmdir(source)
                    else:
                        log.warning(f"Quellordner nicht leer, wird nicht gelöscht: {source}")
                else:
                    shutil.move(source, destination)
        return True
    except OSError as e:
        log.error(f"Daten verschieben fehlgeschlagen: {e}")
        messagebox.showerror("Fehler", f"Daten konnten nicht verschoben werden:\n{e}")
        return False


def create_tray_icon_image():
    """Lädt das Tropfen-Icon für den System Tray (Fallback: blaues Quadrat)."""
    if not HAS_TRAY:
        return None
    if os.path.exists(ICON_PATH):
        try:
            return PilImage.open(ICON_PATH).resize((64, 64))
        except Exception:
            pass
    image = PilImage.new("RGB", (64, 64), color=(0, 120, 212))
    return image


# ============================================================
# Hauptklasse: ElHydroLauncher
# ============================================================

class ElHydroLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("elHydro Server Launcher")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Fenster-Icon setzen
        if IS_WINDOWS and os.path.exists(ICON_PATH):
            try:
                self.iconbitmap(ICON_PATH)
            except tk.TclError:
                pass
        elif not IS_WINDOWS:
            png_path = os.path.join(STATIC_DIR, "elhydro.png")
            if os.path.exists(png_path):
                try:
                    self._icon_photo = tk.PhotoImage(file=png_path)
                    self.iconphoto(True, self._icon_photo)
                except tk.TclError:
                    pass

        # Zustandsvariablen
        self.config_data = load_config()
        self.uvicorn_server = None
        self.uvicorn_thread = None
        self.zeroconf_inst = None
        self.zeroconf_info = None
        self.tray_icon = None
        self.server_url = None
        self._qr_photo = None  # Referenz halten gegen Garbage Collection
        self._server_start_attempts = 0
        self._hide_when_started = False

        # Tkinter-Variablen
        self.var_port = tk.StringVar(value=str(self.config_data["port"]))
        self.var_data_dir = tk.StringVar(value=self.config_data["data_dir"])
        self.var_mdns = tk.BooleanVar(value=self.config_data["mdns_enabled"])
        self.var_mdns_mode = tk.StringVar(value=self.config_data["mdns_mode"])
        self.var_mdns_name = tk.StringVar(value=self.config_data["mdns_custom_name"])
        self.var_tray = tk.BooleanVar(value=self.config_data["minimize_to_tray"])
        self.var_autostart = tk.BooleanVar(value=self.config_data["autostart"])

        # Pflanzen-Presets laden
        self._plant_presets = self._load_presets()

        # Testdaten-Variablen (spiegeln echte Geräte-Einstellungen)
        self.var_td_name = tk.StringVar(value="Testpflanze")
        self.var_td_mac = tk.StringVar(value=self._random_mac())
        self.var_td_preset = tk.StringVar(value=self._plant_presets[0]["name"] if self._plant_presets else "Standard (Normal)")
        self.var_td_target = tk.IntVar(value=45)
        self.var_td_delta = tk.IntVar(value=10)
        self.var_td_offline_sleep = tk.IntVar(value=240) # Minuten
        self.var_td_location_type = tk.StringVar(value="indoor")
        self.var_td_location = tk.StringVar(value="")
        self.var_td_entries = tk.IntVar(value=200)

        # UI aufbauen
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self._build_server_tab()
        self._build_test_data_tab()
        self._build_status_view()

        # Vorschau und Zustände initial aktualisieren
        self._update_preview()
        self._update_mdns_state()

        # Traces für Live-Vorschau
        self.var_port.trace_add("write", lambda *_: self._update_preview())
        self.var_mdns.trace_add("write", lambda *_: self._update_mdns_state())
        self.var_mdns_mode.trace_add("write", lambda *_: self._update_mdns_state())
        self.var_mdns_name.trace_add("write", lambda *_: self._update_preview())

    # --- Einstellungen-Frame ---

    @staticmethod
    def _random_mac():
        """Erzeugt eine zufällige MAC-Adresse im Dummy-Format."""
        import random
        octets = [random.randint(0, 255) for _ in range(6)]
        return ":".join(f"{b:02X}" for b in octets)

    def _load_presets(self):
        """Lädt Pflanzen-Presets aus plant_presets.json."""
        presets_path = os.path.join(self.var_data_dir.get(), "plant_presets.json")
        if not os.path.exists(presets_path):
            presets_path = os.path.join(SCRIPT_DIR, "data", "plant_presets.json")
        try:
            with open(presets_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError, FileNotFoundError):
            return [dict(p) for p in DEFAULT_PRESETS]

    def _build_server_tab(self):
        """Baut den Einstellungen-Frame mit allen Konfigurationsoptionen."""
        self.frame_server = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.frame_server, text="Server")

        # Port
        frame_port = ttk.LabelFrame(self.frame_server, text="Server", padding=10)
        frame_port.pack(fill="x", pady=(0, 10))

        row_port = ttk.Frame(frame_port)
        row_port.pack(fill="x")
        ttk.Label(row_port, text="Port:").pack(side="left")
        ttk.Entry(row_port, textvariable=self.var_port, width=8).pack(side="left", padx=(5, 0))

        self.label_port_hint = ttk.Label(
            frame_port, text="Port 80: Kein Port in URL nötig, evtl. Admin-Rechte erforderlich",
            foreground="orange",
        )
        # Wird nur bei Port 80 angezeigt

        # Datenverzeichnis
        frame_data = ttk.LabelFrame(self.frame_server, text="Datenverzeichnis", padding=10)
        frame_data.pack(fill="x", pady=(0, 10))

        row_data = ttk.Frame(frame_data)
        row_data.pack(fill="x")
        self.entry_data_dir = ttk.Entry(row_data, textvariable=self.var_data_dir, width=35)
        self.entry_data_dir.pack(side="left", fill="x", expand=True)
        ttk.Button(row_data, text="Durchsuchen...", command=self._choose_data_dir).pack(side="left", padx=(5, 0))

        row_config_path = ttk.Frame(frame_data)
        row_config_path.pack(fill="x", pady=(5, 0))
        ttk.Label(row_config_path, text="Konfiguration:", foreground="gray").pack(side="left")
        config_entry = ttk.Entry(row_config_path, foreground="gray")
        config_entry.insert(0, CONFIG_FILE)
        config_entry.config(state="readonly")
        config_entry.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # mDNS
        frame_mdns = ttk.LabelFrame(self.frame_server, text="Netzwerk (mDNS)", padding=10)
        frame_mdns.pack(fill="x", pady=(0, 10))

        state = "normal" if HAS_ZEROCONF else "disabled"
        self.check_mdns = ttk.Checkbutton(
            frame_mdns, text="mDNS aktivieren", variable=self.var_mdns, state=state,
        )
        self.check_mdns.pack(anchor="w")
        if not HAS_ZEROCONF:
            ttk.Label(frame_mdns, text="(zeroconf nicht installiert)", foreground="gray").pack(anchor="w")

        self.radio_hostname = ttk.Radiobutton(
            frame_mdns, text="Hostnamen verwenden", variable=self.var_mdns_mode, value="hostname",
        )
        self.radio_hostname.pack(anchor="w", padx=(20, 0), pady=(5, 0))

        hostname = socket.gethostname()
        self.label_hostname_preview = ttk.Label(frame_mdns, text=f"  \u2192 {hostname}.local:8000", foreground="gray")
        self.label_hostname_preview.pack(anchor="w", padx=(40, 0))

        self.radio_custom = ttk.Radiobutton(
            frame_mdns, text="Eigenen Namen registrieren (Zeroconf)",
            variable=self.var_mdns_mode, value="custom",
        )
        self.radio_custom.pack(anchor="w", padx=(20, 0), pady=(5, 0))

        row_custom = ttk.Frame(frame_mdns)
        row_custom.pack(fill="x", padx=(40, 0))
        ttk.Label(row_custom, text="Name:").pack(side="left")
        self.entry_mdns_name = ttk.Entry(row_custom, textvariable=self.var_mdns_name, width=15)
        self.entry_mdns_name.pack(side="left", padx=(5, 0))

        self.label_custom_preview = ttk.Label(frame_mdns, text="", foreground="gray")
        self.label_custom_preview.pack(anchor="w", padx=(40, 0))

        # Tray + Autostart
        frame_options = ttk.LabelFrame(self.frame_server, text="Optionen", padding=10)
        frame_options.pack(fill="x", pady=(0, 10))

        tray_state = "normal" if HAS_TRAY else "disabled"
        self.check_tray = ttk.Checkbutton(
            frame_options, text="Beim Schlie\u00dfen in System Tray minimieren",
            variable=self.var_tray, state=tray_state,
        )
        self.check_tray.pack(anchor="w")
        if not HAS_TRAY:
            ttk.Label(frame_options, text="(pystray nicht installiert)", foreground="gray").pack(anchor="w")

        self.check_autostart = ttk.Checkbutton(
            frame_options, text="Bei Systemstart automatisch starten",
            variable=self.var_autostart, command=self._on_autostart_changed,
        )
        self.check_autostart.pack(anchor="w", pady=(5, 0))

        # Extras
        frame_extras = ttk.LabelFrame(self.frame_server, text="Extras", padding=10)
        frame_extras.pack(fill="x", pady=(0, 10))

        self.btn_epaper = ttk.Button(
            frame_extras, text="E-Paper Simulator starten",
            command=self._start_epaper_simulator,
            state="normal" if HAS_EPAPER_SIM else "disabled",
        )
        self.btn_epaper.pack(anchor="w")
        if not HAS_EPAPER_SIM:
            ttk.Label(frame_extras, text="(epaper_simulator nicht verfügbar)", foreground="gray").pack(anchor="w")

        # Start-Button
        self.btn_start = ttk.Button(
            self.frame_server, text="\u25b6  Server starten", command=self.start_server,
        )
        self.btn_start.pack(pady=(10, 0), ipadx=20, ipady=5)

    # --- Testdaten-Tab ---

    def _build_test_data_tab(self):
        """Baut den Testdaten-Tab — spiegelt die echten Geräte-Einstellungen."""
        self.frame_test_data = ttk.Frame(self.notebook, padding=15)
        self.notebook.add(self.frame_test_data, text="Testdaten")

        # Gerät
        frame_device = ttk.LabelFrame(self.frame_test_data, text="Gerät", padding=10)
        frame_device.pack(fill="x", pady=(0, 8))

        row_name = ttk.Frame(frame_device)
        row_name.pack(fill="x")
        ttk.Label(row_name, text="Name:").pack(side="left")
        ttk.Entry(row_name, textvariable=self.var_td_name, width=25).pack(side="left", padx=(5, 0))

        row_mac = ttk.Frame(frame_device)
        row_mac.pack(fill="x", pady=(5, 0))
        ttk.Label(row_mac, text="MAC:").pack(side="left")
        ttk.Entry(row_mac, textvariable=self.var_td_mac, width=20).pack(side="left", padx=(5, 5))
        btn_new_mac = ttk.Button(row_mac, text="Neu", width=4, command=lambda: (
            self.var_td_mac.set(self._random_mac()), btn_new_mac.focus_set(),
        ))
        btn_new_mac.pack(side="left")

        # Pflanzentyp (wie in der echten App)
        frame_plant = ttk.LabelFrame(self.frame_test_data, text="Pflanzentyp", padding=10)
        frame_plant.pack(fill="x", pady=(0, 8))

        preset_names = [p["name"] for p in self._plant_presets]
        row_preset = ttk.Frame(frame_plant)
        row_preset.pack(fill="x")
        ttk.Label(row_preset, text="Preset:").pack(side="left")
        self.combo_preset = ttk.Combobox(
            row_preset, textvariable=self.var_td_preset,
            values=preset_names, state="readonly", width=25,
        )
        self.combo_preset.pack(side="left", padx=(5, 0))
        self.combo_preset.bind("<<ComboboxSelected>>", self._on_preset_selected)

        row_target = ttk.Frame(frame_plant)
        row_target.pack(fill="x", pady=(5, 0))
        ttk.Label(row_target, text="Ziel-Bodenfeuchte:").pack(side="left")
        self.label_td_target = ttk.Label(row_target, text="45%", width=5)
        self.label_td_target.pack(side="right")
        self.scale_td_target = ttk.Scale(
            row_target, from_=TARGET_SOIL_MIN, to=TARGET_SOIL_MAX, variable=self.var_td_target, orient="horizontal",
            command=lambda v: self.label_td_target.config(text=f"{int(float(v))}%"),
        )
        self.scale_td_target.pack(side="left", fill="x", expand=True, padx=(5, 5))

        row_delta = ttk.Frame(frame_plant)
        row_delta.pack(fill="x", pady=(5, 0))
        ttk.Label(row_delta, text="Bewässerungs-Delta:").pack(side="left")
        self.label_td_delta = ttk.Label(row_delta, text="10%", width=5)
        self.label_td_delta.pack(side="right")
        ttk.Scale(
            row_delta, from_=IRR_DELTA_MIN, to=IRR_DELTA_MAX, variable=self.var_td_delta, orient="horizontal",
            command=lambda v: self.label_td_delta.config(text=f"{int(float(v))}%"),
        ).pack(side="left", fill="x", expand=True, padx=(5, 5))
        self.label_td_threshold = ttk.Label(frame_plant, text="", foreground="gray")
        self.label_td_threshold.pack(anchor="w", pady=(2, 0))
        ttk.Label(
            frame_plant,
            text="Gilt online und offline — bei Hitze und Trockenheit auch früher",
            foreground="gray",
        ).pack(anchor="w", pady=(2, 0))
        self.var_td_target.trace_add("write", lambda *_: self._update_td_threshold())
        self.var_td_delta.trace_add("write", lambda *_: self._update_td_threshold())
        self._update_td_threshold()

        # ESP32 Offline-Modus
        frame_offline = ttk.LabelFrame(self.frame_test_data, text="ESP32 Offline-Modus", padding=10)
        frame_offline.pack(fill="x", pady=(0, 8))

        row_offline = ttk.Frame(frame_offline)
        row_offline.pack(fill="x")
        ttk.Label(row_offline, text="Offline Sleep:", width=14).pack(side="left")
        ttk.Spinbox(row_offline, from_=10, to=1440, textvariable=self.var_td_offline_sleep, width=6).pack(side="left", padx=(5, 5))
        ttk.Label(row_offline, text="Min.", foreground="gray").pack(side="left")

        # Standort (wie in der echten App)
        frame_location = ttk.LabelFrame(self.frame_test_data, text="Standort", padding=10)
        frame_location.pack(fill="x", pady=(0, 8))

        row_type = ttk.Frame(frame_location)
        row_type.pack(fill="x")
        ttk.Radiobutton(row_type, text="Indoor", variable=self.var_td_location_type,
                         value="indoor", command=self._on_location_type_changed).pack(side="left")
        ttk.Radiobutton(row_type, text="Outdoor", variable=self.var_td_location_type,
                         value="outdoor", command=self._on_location_type_changed).pack(side="left", padx=(15, 0))

        self.frame_td_location = ttk.Frame(frame_location)
        ttk.Label(self.frame_td_location, text="Ort:").pack(side="left")
        ttk.Entry(self.frame_td_location, textvariable=self.var_td_location, width=20).pack(side="left", padx=(5, 0))
        ttk.Label(self.frame_td_location, text="(Stadt oder Koordinaten)", foreground="gray").pack(side="left", padx=(5, 0))
        # Nur bei Outdoor sichtbar
        self._on_location_type_changed()

        # Datenmenge
        frame_amount = ttk.LabelFrame(self.frame_test_data, text="Datenmenge", padding=10)
        frame_amount.pack(fill="x", pady=(0, 8))

        row_amount = ttk.Frame(frame_amount)
        row_amount.pack(fill="x")
        ttk.Label(row_amount, text="Anzahl Einträge:").pack(side="left")
        ttk.Spinbox(
            row_amount, from_=10, to=5000, textvariable=self.var_td_entries, width=8,
        ).pack(side="left", padx=(5, 0))

        # Generieren-Button + Status
        frame_action = ttk.Frame(self.frame_test_data)
        frame_action.pack(fill="x", pady=(5, 0))

        self.btn_generate = ttk.Button(
            frame_action, text="Testdaten generieren", command=self._generate_test_data,
        )
        self.btn_generate.pack(ipadx=15, ipady=4)

        self.label_td_status = ttk.Label(frame_action, text="", foreground="gray")
        self.label_td_status.pack(pady=(5, 0))

    def _on_preset_selected(self, event=None):
        """Aktualisiert Target wenn ein Preset gewählt wird."""
        name = self.var_td_preset.get()
        for preset in self._plant_presets:
            if preset["name"] == name:
                self.var_td_target.set(preset["target_soil_pct"])
                self.label_td_target.config(text=f"{preset['target_soil_pct']}%")
                break

    def _update_td_threshold(self):
        """Berechnet die Bewässerungs-Schwelle live (gleiche Formel wie Brain + Firmware)."""
        threshold = soil_threshold(self.var_td_target.get(), self.var_td_delta.get())
        self.label_td_threshold.config(
            text=f"Bewässerung startet spätestens bei {threshold}% Bodenfeuchte"
        )

    def _on_location_type_changed(self):
        """Zeigt/versteckt das Ort-Feld je nach Indoor/Outdoor."""
        if self.var_td_location_type.get() == "outdoor":
            self.frame_td_location.pack(fill="x", pady=(5, 0))
        else:
            self.frame_td_location.pack_forget()

    def _generate_test_data(self):
        """Startet die Testdaten-Generierung in einem Thread."""
        # Zahlenfelder zuerst prüfen: Bei ungültiger Eingabe wirft Tk einen Fehler,
        # und der Button bliebe sonst auf "Generiere..." stehen
        try:
            offline_min = self.var_td_offline_sleep.get()
            count = self.var_td_entries.get()
        except tk.TclError:
            offline_min = count = None
        if offline_min is None or count is None or not (10 <= offline_min <= 1440) or not (10 <= count <= 5000):
            self.label_td_status.config(
                text="Offline Sleep: 10 bis 1440 Minuten, Anzahl: 10 bis 5000", foreground="red",
            )
            return

        self.btn_generate.config(state="disabled", text="Generiere...")
        self.label_td_status.config(text="", foreground="gray")

        # Sleep-Multiplier und id aus dem gewählten Preset holen
        multiplier = 1.0
        preset_id = None
        preset_name = self.var_td_preset.get()
        for preset in self._plant_presets:
            if preset["name"] == preset_name:
                multiplier = preset.get("sleep_multiplier", 1.0)
                preset_id = preset.get("id")
                break

        config = {
            "name": self.var_td_name.get(),
            "mac": self.var_td_mac.get(),
            "target_soil_pct": self.var_td_target.get(),
            "irrigation_start_delta": self.var_td_delta.get(),
            "offline_sleep_s": offline_min * 60,
            "plant_multiplier": multiplier,
            "preset_id": preset_id,
            "num_entries": count,
            "location_type": self.var_td_location_type.get(),
            "location": self.var_td_location.get() if self.var_td_location_type.get() == "outdoor" else None,
            "data_dir": self.var_data_dir.get(),
        }

        def _run():
            try:
                from tools.generate_dummy_data import generate_device_data
                path, count = generate_device_data(config)
                self.after(0, lambda: self._on_test_data_done(path, count))
            except Exception as e:
                # e existiert nach dem except-Block nicht mehr, der Callback läuft aber später
                error = str(e)
                self.after(0, lambda: self._on_test_data_error(error))

        threading.Thread(target=_run, daemon=True).start()

    def _on_test_data_done(self, path: str, count: int = 0):
        """Callback wenn Testdaten erfolgreich erstellt wurden."""
        self.btn_generate.config(state="normal", text="Testdaten generieren")
        self.label_td_status.config(
            text=f"Erstellt: {count} Einträge in {os.path.basename(path)}", foreground="green",
        )
        # Neue MAC für nächsten Durchlauf
        self.var_td_mac.set(self._random_mac())

    def _on_test_data_error(self, error: str):
        """Callback wenn Testdaten-Generierung fehlschlägt."""
        self.btn_generate.config(state="normal", text="Testdaten generieren")
        self.label_td_status.config(text=f"Fehler: {error}", foreground="red")

    # --- E-Paper Simulator ---

    def _start_epaper_simulator(self):
        """Startet den E-Paper Simulator als integriertes Toplevel-Fenster."""
        try:
            epaper_start_embedded(self)
            log.info("E-Paper Simulator gestartet (integriert)")
        except Exception as e:
            messagebox.showerror("Fehler", f"E-Paper Simulator konnte nicht gestartet werden:\n{e}")

    # --- Status-Frame ---

    def _build_status_view(self):
        """Baut den Status-Frame (nach Server-Start sichtbar)."""
        self.frame_status = ttk.Frame(self, padding=15)
        # Wird erst nach Start eingeblendet

        self.label_status = ttk.Label(
            self.frame_status, text="", font=("Segoe UI", 11), wraplength=350,
        )
        self.label_status.pack(pady=(0, 10))

        self.label_qr = ttk.Label(self.frame_status)
        self.label_qr.pack(pady=(0, 10))

        self.btn_browser = ttk.Button(
            self.frame_status, text="Dashboard im Browser \u00f6ffnen",
            command=lambda: webbrowser.open(self.server_url) if self.server_url else None,
        )
        self.btn_browser.pack(pady=(0, 5), ipadx=10, ipady=3)

        self.btn_stop = ttk.Button(
            self.frame_status, text="\u25a0  Server stoppen", command=self.stop_server,
        )
        self.btn_stop.pack(pady=(5, 0), ipadx=10, ipady=3)

    # --- Vorschau-Aktualisierung ---

    def _update_preview(self):
        """Aktualisiert die URL-Vorschauen basierend auf den aktuellen Einstellungen."""
        try:
            port = int(self.var_port.get())
        except ValueError:
            port = 8000

        # Port-80-Hinweis
        if port == 80:
            self.label_port_hint.pack(anchor="w", pady=(5, 0))
        else:
            self.label_port_hint.pack_forget()

        port_suffix = "" if port == 80 else f":{port}"
        hostname = socket.gethostname()
        name = self.var_mdns_name.get() or "elhydro"

        self.label_hostname_preview.config(text=f"  \u2192 {hostname}.local{port_suffix}")
        self.label_custom_preview.config(text=f"  \u2192 {name}.local{port_suffix}")

    def _update_mdns_state(self):
        """Aktiviert/deaktiviert mDNS-Widgets je nach Checkbox-Status."""
        active = self.var_mdns.get() and HAS_ZEROCONF
        state = "normal" if active else "disabled"
        self.radio_hostname.config(state=state)
        self.radio_custom.config(state=state)

        custom_active = active and self.var_mdns_mode.get() == "custom"
        self.entry_mdns_name.config(state="normal" if custom_active else "disabled")

        self._update_preview()

    def _choose_data_dir(self):
        """Öffnet einen Ordner-Auswahl-Dialog und bietet an, bestehende Daten zu verschieben."""
        new_path = filedialog.askdirectory(
            title="Datenverzeichnis wählen",
            initialdir=self.var_data_dir.get(),
        )
        if not new_path:
            return

        old_path = self.var_data_dir.get()
        if os.path.normpath(new_path) == os.path.normpath(old_path):
            return

        # Prüfen ob im alten Ordner Daten liegen die verschoben werden können
        files = ["device_settings.json", "plant_presets.json", "logs.jsonl"]
        folders = ["measurements"]
        has_data = any(
            os.path.exists(os.path.join(old_path, d)) for d in files + folders
        )

        if has_data:
            answer = messagebox.askyesno(
                "Datenverzeichnis ändern",
                f"Bestehende Daten nach\n{new_path}\nverschieben?",
            )
            if answer:
                if not move_data(old_path, new_path):
                    return  # Verschieben fehlgeschlagen, Pfad nicht ändern

        self.var_data_dir.set(new_path)
        # Config sofort speichern damit der neue Pfad nicht verloren geht
        self.config_data = self._config_from_ui()
        save_config(self.config_data)

    def _on_autostart_changed(self):
        """Wird aufgerufen wenn die Autostart-Checkbox geändert wird."""
        set_autostart(self.var_autostart.get())
        # Sofort speichern, sonst zeigt die Checkbox nach einem Neustart den alten Stand
        self.config_data = self._config_from_ui()
        save_config(self.config_data)

    # --- Config lesen/schreiben ---

    def _config_from_ui(self) -> dict:
        """Liest die aktuellen UI-Werte in ein Config-Dict."""
        try:
            port = int(self.var_port.get())
        except ValueError:
            port = 8000
        return {
            "port": port,
            "data_dir": self.var_data_dir.get(),
            "mdns_enabled": self.var_mdns.get(),
            "mdns_mode": self.var_mdns_mode.get(),
            "mdns_custom_name": self.var_mdns_name.get(),
            "minimize_to_tray": self.var_tray.get(),
            "autostart": self.var_autostart.get(),
        }

    # --- Server starten/stoppen ---

    def start_server(self, hide=False):
        """Validiert Einstellungen und startet den Uvicorn-Server in einem Thread.
        hide: Fenster nach dem Start in den Tray legen bzw. minimieren (Autostart)."""
        # Port validieren
        try:
            port = int(self.var_port.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showerror("Fehler", "Bitte einen gültigen Port (1-65535) eingeben.")
            return

        if not port_available(port):
            messagebox.showerror("Fehler", f"Port {port} ist bereits belegt.")
            return

        # Config speichern
        self.config_data = self._config_from_ui()
        save_config(self.config_data)

        # Datenverzeichnis erstellen und Umgebungsvariable setzen
        data_dir = self.config_data["data_dir"]
        os.makedirs(data_dir, exist_ok=True)
        os.environ["ELHYDRO_DATA_DIR"] = data_dir

        # Gecachte Module entfernen damit DataManager beim Neustart
        # frische Daten aus device_settings.json / measurements/ lädt
        for mod_name in list(sys.modules):
            if mod_name == "main" or mod_name.startswith("src."):
                del sys.modules[mod_name]

        # Uvicorn konfigurieren und starten
        try:
            config = uvicorn.Config("main:app", host="0.0.0.0", port=port, log_level="info", log_config=None)
            self.uvicorn_server = uvicorn.Server(config)
            self.uvicorn_server.install_signal_handlers = lambda: None  # Kein Signal-Handler im Thread
        except Exception as e:
            log.error(f"Uvicorn-Konfiguration fehlgeschlagen: {e}")
            messagebox.showerror("Fehler", f"Server konnte nicht konfiguriert werden:\n{e}")
            return

        self.uvicorn_thread = threading.Thread(target=self.uvicorn_server.run, daemon=True)
        self.uvicorn_thread.start()
        self._hide_when_started = hide

        # UI deaktivieren während wir auf den Server warten
        self.btn_start.config(state="disabled", text="Starte...")
        self._server_start_attempts = 0
        self._wait_for_server()

    def _wait_for_server(self):
        """Pollt den Server-Status und wechselt zur Status-Ansicht wenn bereit."""
        if self.uvicorn_server and self.uvicorn_server.started:
            self._on_server_started()
            return

        # Beendeter Thread heißt: Start fehlgeschlagen (z.B. Port belegt, Importfehler),
        # dann nicht erst die vollen 10 Sekunden warten
        thread_ended = not self.uvicorn_thread.is_alive()
        if thread_ended or self._server_start_attempts >= 50:  # ~10 Sekunden bei 200ms
            if thread_ended:
                log.error("Server-Thread beim Start beendet")
            else:
                log.error("Server-Start Timeout nach 10 Sekunden")
                self.uvicorn_server.should_exit = True
            self.uvicorn_server = None
            self.uvicorn_thread = None
            messagebox.showerror("Fehler", f"Server konnte nicht gestartet werden.\nDetails stehen in:\n{LOG_FILE}")
            self.btn_start.config(state="normal", text="\u25b6  Server starten")
            self._server_start_attempts = 0
        else:
            self._server_start_attempts += 1
            self.after(200, self._wait_for_server)

    def _on_server_started(self):
        """Wird aufgerufen sobald der Server bereit ist."""
        port = self.config_data["port"]
        port_suffix = "" if port == 80 else f":{port}"

        # URL bestimmen
        if self.config_data["mdns_enabled"]:
            if self.config_data["mdns_mode"] == "custom":
                name = self.config_data["mdns_custom_name"] or "elhydro"
                host = f"{name}.local"
            else:
                host = f"{socket.gethostname()}.local"
        else:
            host = get_local_ip()

        self.server_url = f"http://{host}{port_suffix}"

        # Zeroconf registrieren
        self._register_zeroconf()

        # Status-UI anzeigen
        self.label_status.config(text=f"\u2713 Server läuft auf\n{self.server_url}")

        # QR-Code erzeugen
        self._qr_photo = create_qr_image(self.server_url)
        if self._qr_photo:
            self.label_qr.config(image=self._qr_photo)
        else:
            self.label_qr.config(text=f"\n{self.server_url}\n\n(qrcode nicht installiert)")

        # Frames wechseln: Notebook ausblenden, Status einblenden
        self.notebook.pack_forget()
        self.frame_status.pack(fill="both", expand=True)

        # System Tray erstellen
        if self.config_data["minimize_to_tray"] and HAS_TRAY:
            self._create_tray_icon()

        # Beim Autostart läuft der Server im Hintergrund weiter
        if self._hide_when_started:
            if self.tray_icon:
                self.withdraw()
            else:
                self.iconify()

        log.info(f"Server gestartet: {self.server_url}")

    def stop_server(self):
        """Stoppt den Server und kehrt zur Einstellungen-Ansicht zurück."""
        self._unregister_zeroconf()

        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.uvicorn_thread:
            self.uvicorn_thread.join(timeout=5.0)
            self.uvicorn_thread = None
        self.uvicorn_server = None

        if self.tray_icon:
            self.tray_icon.stop()
            self.tray_icon = None

        # Zurück zum Notebook
        self.frame_status.pack_forget()
        self.notebook.pack(fill="both", expand=True)
        self.btn_start.config(state="normal", text="\u25b6  Server starten")
        self.server_url = None

        log.info("Server gestoppt")

    # --- Zeroconf ---

    def _register_zeroconf(self):
        """Registriert den mDNS-Service wenn aktiviert und im Custom-Modus."""
        if not HAS_ZEROCONF:
            return
        if not self.config_data.get("mdns_enabled"):
            return
        if self.config_data.get("mdns_mode") != "custom":
            return

        name = self.config_data.get("mdns_custom_name", "elhydro")
        port = self.config_data.get("port", 8000)
        ip = get_local_ip()

        try:
            self.zeroconf_info = ServiceInfo(
                "_http._tcp.local.",
                f"{name}._http._tcp.local.",
                addresses=[socket.inet_aton(ip)],
                port=port,
                properties={"path": "/"},
                server=f"{name}.local.",
            )
            self.zeroconf_inst = Zeroconf()
            self.zeroconf_inst.register_service(self.zeroconf_info)
            log.info(f"Zeroconf registriert: {name}.local:{port}")
        except NonUniqueNameException:
            messagebox.showwarning(
                "mDNS", f"Der Name '{name}.local' wird bereits im Netzwerk verwendet."
            )
        except Exception as e:
            log.warning(f"Zeroconf-Registrierung fehlgeschlagen: {e}")

    def _unregister_zeroconf(self):
        """Meldet den mDNS-Service ab und schließt Zeroconf."""
        if self.zeroconf_inst:
            try:
                self.zeroconf_inst.unregister_all_services()
                self.zeroconf_inst.close()
            except Exception as e:
                log.warning(f"Zeroconf-Abmeldung fehlgeschlagen: {e}")
            self.zeroconf_inst = None
            self.zeroconf_info = None

    # --- System Tray ---

    def _create_tray_icon(self):
        """Erstellt das System-Tray-Icon mit Kontextmenü."""
        if not HAS_TRAY or self.tray_icon:
            return

        icon_image = create_tray_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Fenster öffnen", lambda: self.after(0, self._show_window), default=True),
            pystray.MenuItem(
                "Dashboard im Browser öffnen",
                lambda: webbrowser.open(self.server_url) if self.server_url else None,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", lambda: self.after(0, self.shutdown)),
        )
        self.tray_icon = pystray.Icon("elHydro", icon_image, "elHydro Server", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_window(self):
        """Stellt das Fenster aus dem System Tray wieder her."""
        self.deiconify()
        self.lift()
        self.focus_force()

    # --- Fenster schließen / Beenden ---

    def _on_close(self):
        """WM_DELETE_WINDOW Handler: In Tray minimieren oder komplett beenden."""
        if self.server_url and self.config_data.get("minimize_to_tray") and HAS_TRAY:
            self.withdraw()
        else:
            self.shutdown()

    def shutdown(self):
        """Fährt alles sauber herunter: Zeroconf, Uvicorn, Tray, Fenster."""
        log.info("Beende elHydro Launcher...")

        self._unregister_zeroconf()

        if self.uvicorn_server:
            self.uvicorn_server.should_exit = True
        if self.uvicorn_thread:
            self.uvicorn_thread.join(timeout=5.0)

        if self.tray_icon:
            self.tray_icon.stop()

        self.destroy()


# ============================================================
# Einstiegspunkt
# ============================================================

if __name__ == "__main__":
    # Einzelinstanz sicherstellen
    _mutex = ensure_single_instance()

    app = ElHydroLauncher()
    # Autostart-Eintrag auffrischen: aktueller Pfad und Startargument, auch wenn
    # er von einer älteren Version oder einem anderen Speicherort stammt
    if app.config_data["autostart"]:
        set_autostart(True)
    # Beim Systemstart gleich den Server starten, damit die Knoten ohne Klick einen Host haben
    if AUTOSTART_ARG in sys.argv[1:]:
        app.after(0, lambda: app.start_server(hide=True))
    app.mainloop()
