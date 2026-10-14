# src/utils/constants.py
# Konstanten: BLE-UUIDs, Dateipfade, Pflanzen-Presets und Standardeinstellungen.
import copy
import os
import json
import tempfile
import time

# Basis UUID: 6E40xxxx-B5A3-F393-E0A9-E50E24DCCA9E

UUID_SVC_CUSTOM        = "6E400040-B5A3-F393-E0A9-E50E24DCCA9E"

# Characteristics
UUID_CHR_MEAS          = "6E400140-B5A3-F393-E0A9-E50E24DCCA9E"  # Notify
UUID_CHR_MEAS_IND      = "6E400640-B5A3-F393-E0A9-E50E24DCCA9E"  # Indicate (mit Empfangsbestätigung)
UUID_CHR_TARGET        = "6E400240-B5A3-F393-E0A9-E50E24DCCA9E"  # Write
UUID_CHR_SLEEP         = "6E400340-B5A3-F393-E0A9-E50E24DCCA9E"  # Write
UUID_CHR_OFFLINE_SLEEP = "6E400440-B5A3-F393-E0A9-E50E24DCCA9E"  # Write
UUID_CHR_TIME          = "6E400540-B5A3-F393-E0A9-E50E24DCCA9E"  # Write
UUID_CHR_IRRIGATION    = "6E400740-B5A3-F393-E0A9-E50E24DCCA9E"  # Write
UUID_CHR_IRR_DELTA     = "6E400840-B5A3-F393-E0A9-E50E24DCCA9E"  # Write

# Pfade
# Datenverzeichnis: Umgebungsvariable hat Vorrang, sonst Fallback auf ./data
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.environ.get("ELHYDRO_DATA_DIR", os.path.join(BASE_DIR, "data"))
SETTINGS_FILE = os.path.join(DATA_DIR, "device_settings.json")
MEASUREMENTS_DIR = os.path.join(DATA_DIR, "measurements")
PRESETS_FILE = os.path.join(DATA_DIR, "plant_presets.json")
LOG_FILE = os.path.join(DATA_DIR, "logs.jsonl")

# Defaults
DEFAULT_TARGET_SOIL = 50
DEFAULT_OFFLINE_SLEEP = 14400   # 4 Stunden
DEFAULT_IRR_DELTA = 10          # Bewässerungs-Delta: Hysterese unter Target (online + offline)

# Eingabegrenzen in Prozent, gleich in API, Dashboard und Launcher
# (test_firmware_sync.py vergleicht sie mit den Formularen des Dashboards)
TARGET_SOIL_MIN, TARGET_SOIL_MAX = 10, 90
IRR_DELTA_MIN, IRR_DELTA_MAX = 5, 50

# BLE Gerätename
DEVICE_NAME = "elHydro-ESP32C6"


def load_plant_presets():
    """Lädt Pflanzen-Presets aus der JSON-Datei."""
    if os.path.exists(PRESETS_FILE):
        try:
            with open(PRESETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Kaputte Datei aufheben, sonst überschreiben die Standard-Presets sie
            os.replace(PRESETS_FILE, f"{PRESETS_FILE}.defekt-{int(time.time())}")
        except IOError:
            pass
    return _default_presets()


def write_json_atomic(path, data, indent=4):
    """Schreibt JSON atomar (temporäre Datei + Umbenennen),
    damit ein Absturz beim Schreiben die bestehende Datei nicht zerstört."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(tmp_path, path)
    except BaseException:
        os.remove(tmp_path)
        raise


def write_plant_presets(presets):
    """Speichert die Presets atomar."""
    write_json_atomic(PRESETS_FILE, presets)


# Standard-Presets, mit denen plant_presets.json beim ersten Start angelegt wird
# (der Launcher nutzt sie auch, solange es die Datei noch nicht gibt)
DEFAULT_PRESETS = [
    {
        "id": "standard",
        "name": "Standard (Normal)",
        "target_soil_pct": 45,
        "sleep_multiplier": 1.0,
        "irrigation_start_delta": DEFAULT_IRR_DELTA
    },
    {
        "id": "durstig",
        "name": "Durstig (Viel Wasser)",
        "target_soil_pct": 65,
        "sleep_multiplier": 0.7,
        "irrigation_start_delta": DEFAULT_IRR_DELTA
    },
    {
        "id": "sukkulente",
        "name": "Sukkulente (Wenig Wasser)",
        "target_soil_pct": 25,
        "sleep_multiplier": 1.5,
        "irrigation_start_delta": DEFAULT_IRR_DELTA
    },
    {
        "id": "custom",
        "name": "Benutzerdefiniert",
        "target_soil_pct": 50,
        "sleep_multiplier": 1.0,
        "irrigation_start_delta": DEFAULT_IRR_DELTA
    }
]


def _default_presets():
    """Erstellt die Standard-Presets und speichert sie."""
    presets = copy.deepcopy(DEFAULT_PRESETS)
    write_plant_presets(presets)
    return presets
