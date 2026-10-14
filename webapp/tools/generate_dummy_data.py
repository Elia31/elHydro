"""
Generiert realistische Dummy-Daten zum Testen der Web-App ohne ESP32-Hardware.

Nutzt die echte Brain-Logik (src/core/brain.py) für Sleep-Dauer und
Bewässerungsentscheidungen. Simuliert LiPo-Entladung, variable Messintervalle,
Offline-Phasen und ESP32-System-Statistiken.

Nutzung:
    CLI:  python tools/generate_dummy_data.py --name "Ficus" --target 45 --entries 200
          (im Ordner webapp/, bei gestopptem Server)
    GUI:  Wird vom Launcher-Tab "Testdaten" aufgerufen
"""

import argparse
import asyncio
import csv
import json
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# Projektwurzel (Parent von tools/) zum Import-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.brain import Brain, BrainDecision, _evap_delta, irrigation_threshold, soil_threshold
from src.core.data_manager import CSV_FIELDS, csv_filename
from src.core.weather import get_weather_for_device
from src.utils.constants import DATA_DIR, write_json_atomic

# --- Konstanten ---

# Gleicher Datenordner wie der Server
DEFAULT_DATA_DIR = Path(DATA_DIR)


# ESP32 Reset Reasons
RESET_DEEPSLEEP = 8
RESET_POWERON = 1
RESET_BROWNOUT = 9


# --- Physik-Simulation ---

def _sim_temperature(hour: float, temp_min: float, temp_max: float,
                     is_outdoor: bool, day_offset: float) -> float:
    """Simuliert Temperatur mit Tages-Sinuskurve und Tages-Drift.

    day_offset ist ein langsam wandernder Wert der sich von Tag zu Tag
    ändert, sodass nicht jeder Tag identisch aussieht.
    """
    temp_mid = (temp_min + temp_max) / 2
    temp_amp = (temp_max - temp_min) / 2
    # Phase: Minimum bei hour=5 (sin=-1), Maximum bei hour=17 (sin=+1)
    daily_cycle = temp_amp * math.sin((hour - 11) * math.pi / 12)
    # Tages-Drift: verschiebt das Tagesmittel (wärmere/kältere Tage)
    temp = temp_mid + day_offset + daily_cycle * (0.6 + 0.4 * abs(day_offset) / max(temp_amp, 1))
    # Sensor-Rauschen
    noise = random.gauss(0, 1.5 if is_outdoor else 0.3)
    return round(temp + noise, 2)


def _sim_humidity(temp: float, is_outdoor: bool) -> float:
    """Simuliert Luftfeuchte, invers korreliert mit Temperatur."""
    # Basis: 55% bei 20°C, steigt bei Kälte, fällt bei Hitze
    base = 55 - (temp - 20) * 1.5
    noise = random.gauss(0, 3.0 if is_outdoor else 1.5)
    return round(max(15, min(95, base + noise)), 2)


def _soil_decay_factor(temp: float, rh: float, is_outdoor: bool,
                       hours_elapsed: float) -> float:
    """Berechnet den Austrocknungs-Faktor für Bodenfeuchte (exponentiell)."""
    # Basis-Trocknungsrate pro Stunde: ~0.5-2% je nach Bedingungen
    base_rate = 0.008  # ~0.8% pro Stunde bei Normalbedingungen
    # Temperatur-Effekt: wärmer = schnellere Trocknung
    temp_factor = 1.0 + max(0, (temp - 20)) * 0.05
    # Luftfeuchte-Effekt: trockene Luft = schnellere Trocknung
    rh_factor = 1.0 + max(0, (50 - rh)) * 0.01
    # Outdoor trocknet schneller (Wind, direkte Sonne)
    outdoor_factor = 1.4 if is_outdoor else 1.0

    rate = base_rate * temp_factor * rh_factor * outdoor_factor
    return math.exp(-rate * hours_elapsed)


def _sim_irrigation_ms(deficit: float) -> int:
    """Berechnet realistische Bewässerungsdauer basierend auf Feuchtigkeitsdefizit.
    ESP32 pumpt in 1-4s Schritten mit 5s Soak-Time dazwischen."""
    if deficit <= 5:
        steps = random.randint(1, 3)
        step_ms = 1000
    elif deficit <= 15:
        steps = random.randint(2, 5)
        step_ms = 2000
    else:
        steps = random.randint(3, 8)
        step_ms = random.choice([2000, 4000])
    return steps * step_ms + random.randint(-500, 500)


def _calc_offline_sleep_s(base_s: int, soil_pct: int, threshold: int,
                          temp: float, rh: float) -> int:
    """Spiegelt calc_offline_sleep_s() aus der ESP32-Firmware.

    Zwei Faktoren:
      1) Soil-Margin:  nah am Threshold → kürzer, weit weg → länger
      2) Evaporation:  linearer Faktor (evap 0→1.0, evap 8→0.5)
    """
    margin = soil_pct - threshold
    sleep_s = base_s

    if margin <= 5:
        sleep_s = base_s // 2
    elif margin > 20:
        sleep_s = base_s * 3 // 2

    evap = _evap_delta(temp, rh)
    sleep_s = sleep_s * (16 - evap) // 16

    min_s = base_s // 4
    return max(sleep_s, min_s)


def _lipo_voltage_drop(irrigated: bool) -> float:
    """Simuliert Spannungsabfall pro Wakeup-Zyklus."""
    base = random.uniform(0.0008, 0.0020)
    if irrigated:
        base += random.uniform(0.002, 0.005)  # Pumpe verbraucht mehr
    return base


# --- Hauptgenerierung ---

def generate_device_data(config: dict) -> tuple[str, int]:
    """
    Generiert realistische Messdaten für ein Gerät.

    Args:
        config: dict mit Schlüsseln:
            name, mac, target_soil_pct, irrigation_start_delta, offline_sleep_s,
            plant_multiplier, preset_id, num_entries,
            location_type ("indoor"/"outdoor"), location, data_dir (optional)

    Returns:
        (Pfad zur erstellten CSV-Datei, Anzahl der Messungen)
    """
    name = config.get("name", "Testpflanze")
    mac = config.get("mac", "AA:BB:CC:DD:EE:FF")
    target = config.get("target_soil_pct", 45)
    delta = config.get("irrigation_start_delta", 10)
    offline_sleep_s = config.get("offline_sleep_s", 14400)
    plant_multiplier = config.get("plant_multiplier", 1.0)
    num_entries = config.get("num_entries", 200)
    is_outdoor = config.get("location_type", "indoor") == "outdoor"
    data_dir = Path(config.get("data_dir", str(DEFAULT_DATA_DIR)))

    # Temperaturbereich automatisch aus Standort ableiten
    if is_outdoor:
        temp_min, temp_max = -5, 35  # Außen: Frost bis Sommerhitze
    else:
        temp_min, temp_max = 18, 26  # Innen: klimatisiert
    device_config = {
        "target_soil_pct": target,
        "irrigation_start_delta": delta,
        "offline_sleep_s": offline_sleep_s,
    }

    # Kalibrierungswerte (pro Gerät leicht unterschiedlich)
    calib_dry = random.randint(2400, 2800)
    calib_wet = random.randint(700, 900)

    brain = Brain()
    rows = []

    # Wetter einmalig für die letzte Messung holen (nur Outdoor + Location gesetzt)
    last_weather = None
    if is_outdoor and config.get("location"):
        try:
            dev_like = {"type": "outdoor", "location": config.get("location")}
            last_weather = asyncio.run(get_weather_for_device(dev_like))
        except Exception:
            last_weather = None

    # --- Anfangszustand ---
    now = time.time()
    # Startzeit: Brain berechnet Sleep dynamisch (~2-12h je nach Zustand).
    # Großzügige Schätzung: durchschnittlich ~5h pro Messung + Nacht + Puffer.
    avg_sleep = 8 * 3600
    avg_with_night = avg_sleep * 0.67 + 10 * 3600 * 0.33
    start_ts = now - int(num_entries * avg_with_night * 1.3)
    current_ts = start_ts

    # Tages-Temperatur-Drift (Random Walk): wärmere und kältere Tage
    temp_amp = (temp_max - temp_min) / 2
    day_temp_offset = random.uniform(-temp_amp * 0.3, temp_amp * 0.3)
    last_day = -1

    soil = target + random.uniform(-5, 10)
    vbat = random.uniform(4.05, 4.20)
    total_irr_ms = 0
    total_wakeups = 0
    total_awake_ms = 0
    ble_success_count = 0
    free_heap = random.randint(170000, 190000)
    uptime_s = 0
    measurement_id = 1
    last_irrigated_ts = 0
    previous_soil = None
    last_awake_ms = random.randint(8000, 12000)
    reset_reason = RESET_POWERON  # Erster Boot

    # Offline-Phasen planen
    # Zufällige BLE-Offline-Blöcke: 2-5 Stück über den gesamten Zeitraum
    total_duration = now - start_ts
    num_offline_blocks = random.randint(1, max(1, num_entries // 80))
    offline_blocks = []
    for _ in range(num_offline_blocks):
        block_start = start_ts + random.uniform(0.1, 0.9) * total_duration
        block_duration = random.uniform(3 * 3600, 18 * 3600)  # 3-18h
        offline_blocks.append((block_start, block_start + block_duration))

    # Batterie-Tod einplanen? (~30% Chance bei langen Zeiträumen)
    battery_death_ts = None
    battery_recharge_ts = None
    if num_entries > 100 and random.random() < 0.3:
        death_point = start_ts + random.uniform(0.4, 0.8) * total_duration
        recharge_gap = random.uniform(12 * 3600, 48 * 3600)
        battery_death_ts = death_point
        battery_recharge_ts = death_point + recharge_gap

    entries_generated = 0

    while entries_generated < num_entries:
        # Nicht über das aktuelle Datum hinaus generieren
        if current_ts > now:
            break

        dt = datetime.fromtimestamp(current_ts)
        hour = dt.hour + dt.minute / 60.0
        current_day = dt.timetuple().tm_yday

        # Tages-Drift: pro neuem Tag leicht verschieben (Random Walk)
        if current_day != last_day:
            day_temp_offset += random.gauss(0, temp_amp * 0.15)
            day_temp_offset = max(-temp_amp * 0.5, min(temp_amp * 0.5, day_temp_offset))
            last_day = current_day

        # --- Batterie-Tod-Phase ---
        if battery_death_ts and battery_recharge_ts:
            if battery_death_ts < current_ts < battery_recharge_ts:
                # Gerät ist aus — springe zur Wiederaufladung
                current_ts = battery_recharge_ts
                vbat = random.uniform(4.05, 4.18)
                reset_reason = RESET_POWERON
                total_wakeups = 0
                ble_success_count = 0
                free_heap = random.randint(170000, 190000)
                uptime_s = 0
                last_awake_ms = random.randint(8000, 12000)
                measurement_id += 1
                continue

        # --- Prüfe ob gerade in einer Offline-Phase ---
        is_offline = False
        for block_start, block_end in offline_blocks:
            if block_start <= current_ts <= block_end:
                is_offline = True
                break

        # --- Physik simulieren ---
        # Zeitdifferenz seit letzter Messung
        if rows:
            hours_elapsed = (current_ts - rows[-1]["timestamp"]) / 3600.0
        else:
            hours_elapsed = 1.0

        temp = _sim_temperature(hour, temp_min, temp_max, is_outdoor, day_temp_offset)
        rh = _sim_humidity(temp, is_outdoor)

        # Bodenfeuchte: exponentieller Abfall
        decay = _soil_decay_factor(temp, rh, is_outdoor, hours_elapsed)
        soil *= decay
        # Kleines Rauschen
        soil += random.gauss(0, 0.3)
        soil = max(3, min(98, soil))

        # --- Entscheidung: Brain (online) vs. ESP32-Eigenlogik (offline) ---
        irrigated = False
        irrigation_ms = 0

        if is_offline:
            # ESP32 offline: kein BLE → kein Brain vom Server.
            # Nutzt adaptive Sleep-Dauer (Soil-Margin + Evaporation) und
            # eigene simple Bewässerungslogik.
            offline_sleep = _calc_offline_sleep_s(
                device_config["offline_sleep_s"], int(soil),
                soil_threshold(target, delta), temp, rh)
            # Wie in der Firmware: Gieß-Schwelle um den Verdunstungs-Index
            # anheben, bei Frost (<= 0 °C) gar nicht gießen
            irr_threshold = irrigation_threshold(target, delta, _evap_delta(temp, rh))
            offline_irrigate = int(soil) < irr_threshold and temp > 0

            if offline_irrigate:
                deficit = max(0, target - soil)
                irrigation_ms = _sim_irrigation_ms(deficit)
                soil_boost = random.uniform(12, 25)
                soil = min(95, soil + soil_boost)
                total_irr_ms += irrigation_ms
                last_irrigated_ts = int(current_ts)
                irrigated = True

            reasoning = f"Offline (kein BLE); Sleep {offline_sleep}s (adaptiv)"
            if irrigated:
                reasoning += f"; Offline-Bewässerung ({int(soil - soil_boost):.0f}% < {irr_threshold}%)"

            decision = BrainDecision(
                sleep_duration_s=offline_sleep,
                should_irrigate=irrigated,
                reasoning=reasoning,
            )
        else:
            # Online: Server-Brain entscheidet
            recent_history = rows[-10:] if rows else []

            def _decide(weather):
                return brain.decide(
                    device_config=device_config,
                    plant_multiplier=plant_multiplier,
                    is_outdoor=is_outdoor,
                    current_soil=int(soil),
                    current_temp=temp,
                    current_rh=rh,
                    weather_data=weather,
                    last_irrigated_ts=last_irrigated_ts,
                    previous_soil=previous_soil,
                    history=recent_history,
                    now_ts=int(current_ts),
                )

            decision = _decide(None)
            # Das Wetter gilt für jetzt: in die Entscheidung der letzten Messung
            # einrechnen (gewünschte Anzahl erreicht oder nächster Zeitpunkt nach jetzt,
            # +60 s für den Jitter unten)
            if last_weather and (entries_generated == num_entries - 1
                                 or current_ts + decision.sleep_duration_s + 60 > now):
                decision = _decide(last_weather)

            if decision.should_irrigate:
                deficit = max(0, target - soil)
                irrigation_ms = _sim_irrigation_ms(deficit)
                soil_boost = random.uniform(12, 25)
                soil = min(95, soil + soil_boost)
                total_irr_ms += irrigation_ms
                last_irrigated_ts = int(current_ts)
                irrigated = True

        # --- Batterie ---
        vbat -= _lipo_voltage_drop(irrigated)
        if vbat < 3.0:
            # Brownout — letzte Messung vor Tod
            if battery_death_ts is None:
                battery_death_ts = current_ts
                battery_recharge_ts = current_ts + random.uniform(12 * 3600, 48 * 3600)
            reset_reason = RESET_BROWNOUT
            vbat = 3.0

        # --- System-Statistiken ---
        total_wakeups += 1
        measurement_id += 1
        awake_ms = random.randint(8000, 15000)
        if irrigated:
            awake_ms += irrigation_ms + 5000 * (irrigation_ms // 4000 + 1)  # Soak-Time
        total_awake_ms += awake_ms
        avg_awake_s = round(total_awake_ms / 1000 / total_wakeups, 1)
        uptime_s += int(hours_elapsed * 3600)
        free_heap -= random.randint(0, 50)  # Langsame Fragmentation
        free_heap = max(80000, free_heap)

        if not is_offline:
            ble_success_count += 1
        ble_pct = round(ble_success_count / total_wakeups * 100, 1) if total_wakeups > 0 else 0

        # --- Sensor-Roh-Wert ---
        soil_raw = int(calib_dry - (soil / 100) * (calib_dry - calib_wet) + random.randint(-20, 20))

        # --- Zeile schreiben ---
        row = {
            "timestamp": int(current_ts),
            "measurement_id": measurement_id,
            "online": not is_offline,
            "soil_pct": int(soil),
            "soil_raw": soil_raw,
            "temp": round(temp, 2),
            "rh": round(rh, 2),
            "vbat": round(vbat, 3),
            "target_soil_pct": target,
            "irrigation_start_delta": delta,
            "offline_sleep_s": device_config["offline_sleep_s"],
            "calib_dry": calib_dry,
            "calib_wet": calib_wet,
            "irrigated": irrigated,
            "irrigation_ms": irrigation_ms,
            "total_irrigation_ms": total_irr_ms,
            "total_wakeups": total_wakeups,
            "avg_awake_s": avg_awake_s,
            "ble_success_pct": ble_pct,
            "total_awake_ms": total_awake_ms,
            "last_awake_time_ms": last_awake_ms,
            "last_sleep_duration_s": decision.sleep_duration_s,
            "uptime_seconds": uptime_s,
            "free_heap_bytes": free_heap,
            "reset_reason": reset_reason,
            "brain_sleep_s": decision.sleep_duration_s if not is_offline else None,
            "brain_irrigate": decision.should_irrigate if not is_offline else None,
            "brain_reasoning": decision.reasoning if not is_offline else None,
        }
        rows.append(row)
        entries_generated += 1

        # Für nächste Iteration
        previous_soil = int(soil)
        last_awake_ms = awake_ms
        reset_reason = RESET_DEEPSLEEP  # Ab jetzt normaler Deep Sleep

        # Nächster Zeitpunkt: Brain-Sleep + kleines Jitter
        if is_offline:
            sleep_s = offline_sleep
        else:
            sleep_s = decision.sleep_duration_s
        jitter = random.randint(-60, 60)
        current_ts += sleep_s + jitter

    # Letzten Eintrag nahe an die Gegenwart schieben, falls die Brain-Sleep-Zeiten
    # im Schnitt kürzer waren als die Start-Schätzung.
    if rows:
        last_ts = rows[-1]["timestamp"]
        target_last_ts = int(now) - random.randint(300, 7200)
        shift = target_last_ts - last_ts
        if shift > 0:
            for row in rows:
                row["timestamp"] += shift

    # --- CSV schreiben ---
    measurements_dir = data_dir / "measurements"
    measurements_dir.mkdir(parents=True, exist_ok=True)

    csv_path = measurements_dir / csv_filename(mac)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    # --- device_settings.json aktualisieren ---
    settings_path = data_dir / "device_settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            settings = {}
    else:
        settings = {}

    settings[mac] = {
        "name": name,
        "preset_id": config.get("preset_id", "standard"),
        "type": "outdoor" if is_outdoor else "indoor",
        "location": config.get("location") or (None if not is_outdoor else None),
        "config": device_config,
        "pending": {
            "target_soil_pct": None,
            "irrigation_start_delta": None,
            "offline_sleep_s": None,
        },
        "last_seen": rows[-1]["timestamp"] if rows else 0,
    }
    if last_weather:
        settings[mac]["last_weather"] = {
            **last_weather,
            "fetched_at": int(time.time()),
        }

    write_json_atomic(str(settings_path), settings)

    return str(csv_path), len(rows)


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="elHydro Dummy-Daten Generator")
    parser.add_argument("--name", default="Testpflanze", help="Pflanzenname")
    parser.add_argument("--mac", default=None, help="MAC-Adresse (default: zufällig)")
    parser.add_argument("--target", type=int, default=45, help="Ziel-Bodenfeuchte %%")
    parser.add_argument("--delta", type=int, default=10, help="Bewässerungs-Delta %%")
    parser.add_argument("--multiplier", type=float, default=1.0, help="Pflanzen-Multiplikator (0.7-1.5)")
    parser.add_argument("--offline-sleep", type=int, default=240, help="Offline Sleep in Minuten")
    parser.add_argument("--entries", type=int, default=200, help="Anzahl Einträge")
    parser.add_argument("--outdoor", action="store_true", help="Außenpflanze")
    parser.add_argument("--location", default=None, help="Ort/Koordinaten (nur für --outdoor, z.B. 'Berlin' oder '52.52,13.41')")
    parser.add_argument("--data-dir", default=None,
                        help=f"Datenverzeichnis (Standard: {DEFAULT_DATA_DIR}, wie bei python main.py)")
    args = parser.parse_args()

    if args.mac is None:
        octets = [random.randint(0, 255) for _ in range(6)]
        args.mac = ":".join(f"{b:02X}" for b in octets)

    config = {
        "name": args.name,
        "mac": args.mac,
        "target_soil_pct": args.target,
        "irrigation_start_delta": args.delta,
        "offline_sleep_s": args.offline_sleep * 60,
        "plant_multiplier": args.multiplier,
        "num_entries": args.entries,
        "location_type": "outdoor" if args.outdoor else "indoor",
        "location": args.location if args.outdoor else None,
    }
    if args.data_dir:
        config["data_dir"] = args.data_dir

    print(f"Generiere Daten für '{args.name}' ({args.mac})...")
    pfad, anzahl = generate_device_data(config)
    print(f"  -> {anzahl} Messwerte in {pfad}")
    # Ein laufender Server kennt das neue Gerät nicht und überschreibt
    # device_settings.json beim nächsten Speichern mit seinem alten Stand
    print("\nFertig! Server jetzt (neu) starten, damit er die Testdaten lädt (im Ordner webapp/):")
    if args.data_dir:
        print(f"  ELHYDRO_DATA_DIR={args.data_dir} python main.py")
    else:
        print("  python main.py")


if __name__ == "__main__":
    main()
