# src/core/data_manager.py
# Datenpersistenz: lädt/speichert Geräteeinstellungen, Messwerte, Pflanzen-Presets und CSV-Logs.
import json
import os
import csv
import time
from collections import deque
from src.utils.constants import (
    SETTINGS_FILE, MEASUREMENTS_DIR, DATA_DIR,
    load_plant_presets, DEFAULT_IRR_DELTA, DEFAULT_OFFLINE_SLEEP,
)


class DataManager:
    def __init__(self):
        os.makedirs(MEASUREMENTS_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)
        self.settings = {}
        self.load_settings()

    def load_settings(self):
        """Lädt die device_settings.json."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self.settings = json.load(f)
            except json.JSONDecodeError:
                self.settings = {}
        else:
            self.settings = {}

    def save_settings(self):
        """Speichert die Settings zurück in die Datei."""
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=4, ensure_ascii=False)

    def get_device(self, mac):
        return self.settings.get(mac)

    def get_all_devices(self):
        return self.settings

    def add_or_update_device(self, mac, name, plant_type, is_outdoor, location=None):
        """Registriert ein neues Gerät oder aktualisiert Metadaten."""
        presets = load_plant_presets()
        preset_map = {p["name"]: p for p in presets}

        if mac not in self.settings:
            preset = preset_map.get(plant_type, {})
            start_target = preset.get("target_soil_pct", 50)

            self.settings[mac] = {
                "config": {
                    "target_soil_pct": start_target,
                    "irrigation_start_delta": DEFAULT_IRR_DELTA,
                    "offline_sleep_s": DEFAULT_OFFLINE_SLEEP,
                },
                "pending": {
                    "target_soil_pct": start_target,
                    "irrigation_start_delta": DEFAULT_IRR_DELTA,
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
        self.settings[mac]["plant_type"] = plant_type
        self.settings[mac]["type"] = "outdoor" if is_outdoor else "indoor"
        self.settings[mac]["location"] = location
        self.save_settings()

    def update_and_queue(self, mac, key, value):
        """Aktualisiert die Config sofort und queued die Änderung für den nächsten BLE-Sync."""
        if mac in self.settings:
            if key in self.settings[mac]["config"]:
                self.settings[mac]["config"][key] = value
            self.settings[mac]["pending"][key] = value
            self.save_settings()

    def clear_pending(self, mac, key):
        """Löscht einen Pending-Eintrag nach erfolgreichem Senden."""
        if mac in self.settings:
            self.settings[mac]["pending"][key] = None
            self.save_settings()

    def update_last_seen(self, mac):
        if mac in self.settings:
            self.settings[mac]["last_seen"] = int(time.time())
            self.save_settings()

    def set_last_irrigated(self, mac):
        """Setzt den Zeitstempel der letzten Bewässerung (für Cooldown)."""
        if mac in self.settings:
            self.settings[mac]["last_irrigated_ts"] = int(time.time())
            self.save_settings()

    def update_first_setup(self, mac, flag):
        """Markiert einen First-Setup-Schritt als erledigt."""
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
        filepath = os.path.join(MEASUREMENTS_DIR, f"{mac.replace(':', '_')}.csv")
        file_exists = os.path.exists(filepath)

        fieldnames = [
            "timestamp", "measurement_id", "online", "soil_pct", "soil_raw",
            "temp", "rh", "vbat", "target_soil_pct", "irrigation_start_delta",
            "offline_sleep_s", "calib_dry", "calib_wet",
            "irrigated", "irrigation_ms", "total_irrigation_ms",
            "total_wakeups", "avg_awake_s", "ble_success_pct",
            "total_awake_ms", "last_awake_time_ms",
            "last_sleep_duration_s", "uptime_seconds", "free_heap_bytes",
            "reset_reason",
            "brain_sleep_s", "brain_irrigate", "brain_reasoning",
        ]

        try:
            with open(filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()

                row = {k: data_dict.get(k) for k in fieldnames if k in data_dict}
                # 0/None = Zeit unbekannt → bleibt leer in CSV
                if row.get("timestamp") in (0, None):
                    row["timestamp"] = ""
                writer.writerow(row)
        except Exception as e:
            print(f"Fehler beim Schreiben der CSV für {mac}: {e}")

    def get_history(self, mac, limit=None, from_ts=0):
        """Liest die letzten `limit` Messwerte aus der CSV, optional ab from_ts."""
        filepath = os.path.join(MEASUREMENTS_DIR, f"{mac.replace(':', '_')}.csv")
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
                    return data[-limit:]

                # Ohne Zeitfilter: nur die letzten `limit` Zeilen behalten
                ring = deque(maxlen=limit)
                for row in reader:
                    _cast_row(row)
                    ring.append(row)
                return list(ring)

        except Exception as e:
            print(f"Fehler beim Lesen der History für {mac}: {e}")
            return []

    def get_measurements_paginated(self, mac, limit=100, offset=0):
        """Liest Messwerte paginiert, neueste zuerst."""
        filepath = os.path.join(MEASUREMENTS_DIR, f"{mac.replace(':', '_')}.csv")
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
            print(f"Fehler beim Lesen der Messdaten für {mac}: {e}")
            return {"total": 0, "offset": offset, "limit": limit, "rows": []}

    def get_csv_path(self, mac):
        """Gibt den Pfad zur CSV-Datei zurück."""
        path = os.path.join(MEASUREMENTS_DIR, f"{mac.replace(':', '_')}.csv")
        return path if os.path.exists(path) else None

    def delete_device(self, mac):
        if mac in self.settings:
            del self.settings[mac]
            self.save_settings()

        csv_path = os.path.join(MEASUREMENTS_DIR, f"{mac.replace(':', '_')}.csv")
        if os.path.exists(csv_path):
            try:
                os.remove(csv_path)
            except Exception as e:
                print(f"Fehler beim Löschen der CSV: {e}")


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
    bool_fields = ["online", "irrigated"]

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
