# src/core/data_manager.py
# Datenpersistenz: lädt/speichert Geräteeinstellungen, Messwerte, Pflanzen-Presets und CSV-Logs.
import copy
import json
import logging
import os
import csv
import re
import tempfile
import threading
import time
from collections import deque
from src.utils.constants import (
    SETTINGS_FILE, MEASUREMENTS_DIR, DATA_DIR,
    load_plant_presets, write_json_atomic,
    DEFAULT_TARGET_SOIL, DEFAULT_IRR_DELTA, DEFAULT_OFFLINE_SLEEP,
)

logger = logging.getLogger("DataManager")


# Spalten der Mess-CSV (auch vom Testdaten-Generator verwendet). Neue Spalten nur
# hinten anhängen: Bestehende Dateien bekommen sie beim nächsten Schreiben dazu.
CSV_FIELDS = [
    "timestamp", "measurement_id", "online", "soil_pct", "soil_raw",
    "temp", "rh", "vbat", "target_soil_pct", "irrigation_start_delta",
    "offline_sleep_s", "calib_dry", "calib_wet",
    "irrigated", "irrigation_ms", "total_irrigation_ms",
    "total_wakeups", "avg_awake_s", "ble_success_pct",
    "total_awake_ms", "last_awake_time_ms",
    "last_sleep_duration_s", "uptime_seconds", "free_heap_bytes",
    "reset_reason",
    "brain_sleep_s", "brain_irrigate", "brain_reasoning",
    "pump_dry",
]


def csv_filename(mac):
    """Dateiname der Mess-CSV eines Geräts. Alles außer Buchstaben, Ziffern und '-'
    wird zu '_' (AA:BB:… → AA_BB_…), damit die Adresse keinen Pfad wie
    '..\\' oder '\\\\server\\share' ergeben kann."""
    return re.sub(r"[^0-9A-Za-z-]", "_", mac) + ".csv"


def _csv_path(mac):
    """Pfad zur Mess-CSV eines Geräts."""
    return os.path.join(MEASUREMENTS_DIR, csv_filename(mac))


def _csv_header(filepath):
    """Spalten, mit denen in eine bestehende CSV geschrieben wird. Fehlen der Datei
    Spalten aus CSV_FIELDS (ältere Version), wird sie atomar um diese ergänzt.
    Klappt das nicht, wird mit den alten Spalten weitergeschrieben."""
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        header = next(csv.reader(f), [])
    missing = [k for k in CSV_FIELDS if k not in header]
    if not header or not missing:
        return header

    new_header = header + missing
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(filepath), prefix=f".{os.path.basename(filepath)}.", suffix=".tmp"
    )
    try:
        with open(filepath, "r", newline="", encoding="utf-8") as src, \
                os.fdopen(fd, "w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=new_header, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv.DictReader(src))
        os.replace(tmp_path, filepath)
        return new_header
    except Exception as e:
        # z. B. unter Windows, wenn die Datei gerade gelesen wird
        os.remove(tmp_path)
        logger.warning(f"Neue Spalten für {filepath} nicht ergänzt: {e}")
        return header


class DataManager:
    def __init__(self):
        os.makedirs(MEASUREMENTS_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)
        self.settings = {}
        # REST-Routen laufen im Threadpool, der BLE-Worker im Event-Loop. Jeder Zugriff
        # auf self.settings läuft deshalb unter diesem Lock, sonst kann json.dump auf ein
        # Dict treffen, das ein anderer Thread gerade ändert.
        self._lock = threading.RLock()
        self.load_settings()

    def load_settings(self):
        """Lädt die device_settings.json."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                # Kaputte Datei aufheben, sonst überschreibt sie das nächste Speichern
                backup = f"{SETTINGS_FILE}.defekt-{int(time.time())}"
                os.replace(SETTINGS_FILE, backup)
                logger.warning(f"device_settings.json unlesbar ({e}), gesichert als {backup}")
                self.settings = {}
        else:
            self.settings = {}
        self._migrate_preset_names()

    def _migrate_preset_names(self):
        """Frühere Versionen merkten sich den Preset-Namen (plant_type) statt der id.
        Ein Name ohne passendes Preset wird zu preset_id None (Pflanzenfaktor 1,0)."""
        old = [dev for dev in self.settings.values() if "plant_type" in dev]
        if not old:
            return
        ids_by_name = {p.get("name"): p.get("id") for p in load_plant_presets()}
        for dev in old:
            dev.setdefault("preset_id", ids_by_name.get(dev.pop("plant_type")))
        self.save_settings()

    def save_settings(self):
        """Speichert die Settings atomar (temporäre Datei + Umbenennen),
        damit ein Absturz beim Schreiben die bestehende Datei nicht zerstört."""
        with self._lock:
            write_json_atomic(SETTINGS_FILE, self.settings)

    def get_device(self, mac):
        """Kopie der Einstellungen eines Geräts (None, wenn unbekannt). Geändert wird
        nur über die Methoden hier, damit jede Änderung unter dem Lock passiert."""
        with self._lock:
            return copy.deepcopy(self.settings.get(mac))

    def get_all_devices(self):
        with self._lock:
            return copy.deepcopy(self.settings)

    def add_or_update_device(self, mac, name, preset_id, is_outdoor, location=None):
        """Registriert ein neues Gerät oder aktualisiert Metadaten."""
        presets = load_plant_presets()
        preset_map = {p["id"]: p for p in presets}

        with self._lock:
            if mac not in self.settings:
                preset = preset_map.get(preset_id, {})
                start_target = preset.get("target_soil_pct", DEFAULT_TARGET_SOIL)
                start_delta = preset.get("irrigation_start_delta", DEFAULT_IRR_DELTA)

                self.settings[mac] = {
                    "config": {
                        "target_soil_pct": start_target,
                        "irrigation_start_delta": start_delta,
                        "offline_sleep_s": DEFAULT_OFFLINE_SLEEP,
                    },
                    "pending": {
                        "target_soil_pct": start_target,
                        "irrigation_start_delta": start_delta,
                        "offline_sleep_s": DEFAULT_OFFLINE_SLEEP,
                    },
                    "first_setup": {
                        "target_sent": False,
                        "offline_sleep_sent": False,
                        "time_sent": False,
                        "completed": False,
                    },
                    "last_seen": 0,
                    "last_irrigated_ts": 0,
                }

            self.settings[mac]["name"] = name
            self.settings[mac]["preset_id"] = preset_id
            self.settings[mac]["type"] = "outdoor" if is_outdoor else "indoor"
            self.settings[mac]["location"] = location
            self.save_settings()

    def update_device(self, mac, **fields):
        """Setzt Felder eines Geräts (z. B. preset_id, type, location, notes, last_weather).
        Gibt False zurück, wenn das Gerät unbekannt ist."""
        with self._lock:
            if mac not in self.settings:
                return False
            self.settings[mac].update(fields)
            self.save_settings()
            return True

    def update_and_queue(self, mac, key, value):
        """Aktualisiert die Config sofort und queued die Änderung für den nächsten BLE-Sync."""
        with self._lock:
            if mac in self.settings:
                if key in self.settings[mac]["config"]:
                    self.settings[mac]["config"][key] = value
                self.settings[mac]["pending"][key] = value
                self.save_settings()

    def clear_pending(self, mac, key):
        """Löscht einen Pending-Eintrag nach erfolgreichem Senden."""
        with self._lock:
            if mac in self.settings:
                self.settings[mac]["pending"][key] = None
                self.save_settings()

    def update_last_seen(self, mac):
        with self._lock:
            if mac in self.settings:
                self.settings[mac]["last_seen"] = int(time.time())
                self.save_settings()

    def set_last_irrigated(self, mac):
        """Setzt den Zeitstempel der letzten Bewässerung (für Cooldown)."""
        with self._lock:
            if mac in self.settings:
                self.settings[mac]["last_irrigated_ts"] = int(time.time())
                self.save_settings()

    def set_pump_dry(self, mac, dry):
        """Merkt sich, ob die letzte Bewässerung ohne Wirkung blieb (Tank leer?).
        Gibt True zurück, wenn sich der Zustand geändert hat."""
        with self._lock:
            if mac not in self.settings or bool(self.settings[mac].get("pump_dry")) == dry:
                return False
            self.settings[mac]["pump_dry"] = dry
            self.save_settings()
            return True

    def update_first_setup(self, mac, flag):
        """Markiert einen First-Setup-Schritt als erledigt."""
        with self._lock:
            if mac not in self.settings:
                return
            fs = self.settings[mac].get("first_setup")
            if not fs or fs.get("completed"):
                return
            fs[flag] = True
            # Alle drei gesendet → Setup abgeschlossen
            if fs.get("target_sent") and fs.get("offline_sleep_sent") and fs.get("time_sent"):
                fs["completed"] = True
            self.save_settings()

    def reconstruct_timestamps(self, buffered, online):
        """
        Rekonstruiert Timestamps für Messungen mit unix_time=0.

        Die Online-Messung (gerade live) bekommt die aktuelle Python-Zeit
        als Anker. Von dort werden gebufferte Messungen rückwärts berechnet
        anhand von last_sleep_duration_s, last_awake_time_ms und reset_reason.

        Modifiziert die Dicts in-place.
        """
        ESP_RST_DEEPSLEEP = 8
        if not buffered and not online:
            return

        # Anker: Online-Messung bekommt Python-Serverzeit
        if online and online.get("timestamp") in (0, None):
            online["timestamp"] = int(time.time())

        # Ohne Anker keine Rückrechnung möglich → append_measurement Fallback
        if not online or online.get("timestamp") in (0, None):
            return

        # Alle Messungen chronologisch: älteste zuerst, online zuletzt
        all_meas = list(buffered) + [online]

        # Vom Anker (letztes Element) rückwärts iterieren
        for i in range(len(all_meas) - 2, -1, -1):
            current = all_meas[i]
            successor = all_meas[i + 1]

            # Nur Messungen mit ungültigem Timestamp korrigieren
            if current.get("timestamp") not in (0, None):
                continue

            # Nachfolger braucht gültigen Timestamp als Referenz
            if successor.get("timestamp") in (0, None, ""):
                current["timestamp"] = None  # unbekannt
                continue

            # Rückrechnung nur wenn Nachfolger planmäßig aus Deep Sleep kam
            if successor.get("reset_reason") != ESP_RST_DEEPSLEEP:
                current["timestamp"] = None  # Kette unterbrochen
                continue

            sleep_s = successor.get("last_sleep_duration_s", 0)
            awake_ms = successor.get("last_awake_time_ms", 0)

            calculated = successor["timestamp"] - sleep_s - (awake_ms / 1000)
            current["timestamp"] = max(0, int(calculated))

    def append_measurement(self, mac, data_dict):
        """Schreibt Messdaten in die CSV."""
        filepath = _csv_path(mac)

        try:
            header = _csv_header(filepath) if os.path.exists(filepath) else []
            with open(filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=header or CSV_FIELDS, extrasaction="ignore")
                if not header:
                    writer.writeheader()

                row = {k: data_dict.get(k) for k in CSV_FIELDS if k in data_dict}
                # 0/None = Zeit unbekannt → bleibt leer in CSV
                if row.get("timestamp") in (0, None):
                    row["timestamp"] = ""
                writer.writerow(row)
        except Exception as e:
            logger.error(f"Fehler beim Schreiben der CSV für {mac}: {e}")

    def get_history(self, mac, limit=None, from_ts=0):
        """Liest die letzten `limit` Messwerte aus der CSV, optional ab from_ts."""
        filepath = _csv_path(mac)
        if not os.path.exists(filepath):
            return []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)

                if from_ts > 0:
                    # Mit Zeitfilter: nur passende Zeilen sammeln
                    data = []
                    for row in reader:
                        _cast_row(row)
                        if (row.get("timestamp") or 0) >= from_ts:
                            data.append(row)
                    return data[-limit:] if limit else data

                # Ohne Zeitfilter: nur die letzten `limit` Zeilen behalten
                ring = deque(maxlen=limit or None)
                for row in reader:
                    _cast_row(row)
                    ring.append(row)
                return list(ring)

        except Exception as e:
            logger.error(f"Fehler beim Lesen der History für {mac}: {e}")
            return []

    def get_measurements_paginated(self, mac, limit=100, offset=0):
        """Liest Messwerte paginiert, neueste zuerst."""
        filepath = _csv_path(mac)
        if not os.path.exists(filepath):
            return {"total": 0, "offset": offset, "limit": limit, "rows": []}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows = []
                for row in reader:
                    _cast_row(row)
                    all_rows.append(row)

            all_rows.reverse()
            total = len(all_rows)
            rows = all_rows[offset:offset + limit]
            return {"total": total, "offset": offset, "limit": limit, "rows": rows}

        except Exception as e:
            logger.error(f"Fehler beim Lesen der Messdaten für {mac}: {e}")
            return {"total": 0, "offset": offset, "limit": limit, "rows": []}

    def get_csv_path(self, mac):
        """Gibt den Pfad zur CSV-Datei zurück."""
        path = _csv_path(mac)
        return path if os.path.exists(path) else None

    def delete_device(self, mac):
        with self._lock:
            if mac in self.settings:
                del self.settings[mac]
                self.save_settings()

        csv_path = _csv_path(mac)
        if os.path.exists(csv_path):
            try:
                os.remove(csv_path)
            except Exception as e:
                logger.error(f"Fehler beim Löschen der CSV: {e}")


def _cast_row(row):
    """Konvertiert CSV-Strings in passende Python-Typen."""
    int_fields = [
        "timestamp", "measurement_id", "soil_pct", "soil_raw",
        "target_soil_pct", "irrigation_start_delta", "offline_sleep_s",
        "calib_dry", "calib_wet", "irrigation_ms", "total_irrigation_ms",
        "total_wakeups", "total_awake_ms", "last_awake_time_ms",
        "last_sleep_duration_s", "uptime_seconds", "free_heap_bytes",
        "reset_reason",
    ]
    float_fields = ["temp", "rh", "vbat", "avg_awake_s", "ble_success_pct"]
    bool_fields = ["online", "irrigated", "pump_dry"]

    for field in int_fields:
        if field in row and row[field]:
            try:
                row[field] = int(float(row[field]))
            except ValueError:
                pass

    for field in float_fields:
        if field in row and row[field]:
            try:
                row[field] = float(row[field])
            except ValueError:
                pass

    for field in bool_fields:
        if field in row:
            row[field] = row[field] in ("True", "true", "1", True)

    # Leere Zahlenfelder (Sensorfehler, unbekannte Zeit) als None liefern,
    # sonst zeigt das Dashboard für "" eine 0 an
    for field in int_fields + float_fields:
        if row.get(field) == "":
            row[field] = None
