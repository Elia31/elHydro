"""
Entscheidungslogik: Berechnet Schlafzeit und Bewässerungsentscheidung.

Pipeline: Trocknungsraten-Vorhersage → Bodentrend → Pflanzenfaktor →
Temperatur/Verdunstung → Wetter → Nachtmodus → Limits → Bewässerungsschwelle.

Sicherheitsmechanismen: Frost-Sperre, Cooldown nach Bewässerung,
Regen-Überspringung und Alerts bei kritischen Zuständen.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MIN_SLEEP_S = 600               # 10 Minuten (globales Minimum nach allen Multiplikatoren)
MAX_SLEEP_S = 86400             # 24 Stunden
COOLDOWN_SECONDS = 7200         # 2 Stunden nach Bewässerung
BELOW_THRESHOLD_SLEEP_S = 3600  # 1 Stunde fix wenn unter Schwelle (Tank leer, Pumpe kaputt)
VERIFICATION_SLEEP_S = 1800     # 30 Minuten nach Bewässerung zur Verifikation
DEFAULT_BASE_SLEEP_S = 7200     # 2 Stunden Fallback ohne Messhistorie
DRYING_SAFETY_FACTOR = 0.7      # 70% der vorhergesagten Zeit → 30% Sicherheitsmarge

# Schwellenwert-Sicherung: verhindert dass durch großes Delta die
# Bewässerung nie auslöst. Schwelle = max(target - delta, target * 20%, 5%)
IRR_THRESHOLD_TARGET_RATIO = 0.2  # Schwelle mind. 20% vom Target
IRR_THRESHOLD_MIN_ABS = 5         # Absolutes Minimum 5%
# Bis 2 % unter dem Ziel gießt die Firmware nicht (IRR_TARGET_TOLERANCE_PCT),
# höher darf die Schwelle auch mit Verdunstungszuschlag nicht liegen
IRR_TARGET_TOLERANCE_PCT = 2

# Frost-Sperre: Wasser gefriert, Pumpe könnte Schaden nehmen
FROST_TEMP_C = 0.0

# Evaporations-Lookup: Temp × Luftfeuchte → Schwellen-Anhebung in Prozentpunkten
# Hohe Temp + niedrige Luftfeuchte = schnelle Austrocknung = früher gießen
EVAP_TABLE = [
    #  rh>70  rh40-70  rh<40
    [  0,     1,       2  ],   # <15°C
    [  1,     3,       5  ],   # 15-29°C
    [  2,     5,       8  ],   # >=30°C
]


@dataclass
class BrainDecision:
    sleep_duration_s: int
    should_irrigate: bool
    reasoning: str
    alerts: list = field(default_factory=list)


def _target_min(target):
    """Untergrenze jeder Schwelle: 20 % vom Ziel, mindestens 5 %."""
    return max(int(target * IRR_THRESHOLD_TARGET_RATIO), IRR_THRESHOLD_MIN_ABS)


def soil_threshold(target, delta):
    """Gieß-Schwelle ohne Verdunstung: max(target - delta, 20 % vom Ziel, 5 %).
    Darunter gilt der Boden als zu trocken (Schlafdauer, Nachtmodus, Anzeige)."""
    return max(target - delta, _target_min(target))


def irrigation_threshold(target, delta, evap_adj=0):
    """Schwelle, unter der gegossen wird: um den Verdunstungszuschlag angehoben,
    höchstens Ziel - 2 %. Gleiche Rechnung wie die Offline-Logik der Firmware.
    Ohne die Obergrenze läge die Schwelle bei kleinem Delta über dem Ziel,
    und es würde bei vollem Boden gegossen."""
    return min(max(target - delta + evap_adj, _target_min(target)),
               target - IRR_TARGET_TOLERANCE_PCT)


def _evap_delta(temp_c, rh_pct):
    """Evaporations-Anpassung aus Temp × Luftfeuchte Lookup-Tabelle."""
    if temp_c is None or rh_pct is None:
        return 0
    ti = 0 if temp_c < 15 else (1 if temp_c < 30 else 2)
    ri = 0 if rh_pct > 70 else (1 if rh_pct >= 40 else 2)
    return EVAP_TABLE[ti][ri]


class Brain:
    """
    Berechnet die optimale Schlafdauer und Bewässerungsentscheidung
    basierend auf Trocknungsrate, Pflanzenprofil, Umgebung und Wetter.
    """

    @staticmethod
    def _compute_drying_rate(history):
        """
        Berechnet die Trocknungsrate in %/Stunde aus der Messhistorie.

        Nutzt nur Segmente wo der Boden trocknet (überspringt
        Bewässerungssprünge und lange Lücken). Neuere Messungen
        werden stärker gewichtet.

        Returns: float > 0 wenn Trocknung erkannt, sonst 0.0
        """
        if not history or len(history) < 2:
            return 0.0

        valid_rates = []
        for i in range(len(history) - 1, 0, -1):
            curr = history[i]
            prev = history[i - 1]

            curr_soil = curr.get("soil_pct")
            prev_soil = prev.get("soil_pct")
            curr_ts = curr.get("timestamp") or 0
            prev_ts = prev.get("timestamp") or 0

            if None in (curr_soil, prev_soil) or curr_ts <= prev_ts:
                continue

            hours = (curr_ts - prev_ts) / 3600.0
            if hours <= 0 or hours > 48:
                continue

            delta_soil = prev_soil - curr_soil  # positiv = Trocknung

            # Bewässerungssprünge überspringen (Boden steigt >3%)
            if delta_soil < -3:
                continue

            if delta_soil > 0:
                valid_rates.append(delta_soil / hours)

        if not valid_rates:
            return 0.0

        # Gewichteter Durchschnitt: neuere Segmente zählen mehr
        weights = [1.0 / (i + 1) for i in range(len(valid_rates))]
        total_weight = sum(weights)
        weighted_rate = sum(r * w for r, w in zip(valid_rates, weights)) / total_weight

        return max(0.0, weighted_rate)

    def decide(self, *, device_config, plant_multiplier=1.0,
               is_outdoor=False, current_soil, current_temp,
               current_rh=None, weather_data=None, last_irrigated_ts=0,
               previous_soil=None, history=None,
               now_ts=None) -> BrainDecision:
        """
        Einheitliche Entscheidung für Sleep + Bewässerung.

        Args:
            device_config: dict mit target_soil_pct, irrigation_start_delta
            plant_multiplier: float (0.7-1.5) aus Preset
            is_outdoor: bool
            current_soil: int (0-100)
            current_temp: float oder None
            current_rh: float oder None (Luftfeuchte 0-100)
            weather_data: dict von WeatherService oder None
            last_irrigated_ts: int Unix-Timestamp der letzten Bewässerung
            previous_soil: int oder None (vorherige Messung)
            history: list[dict] der letzten ~10 Messungen für Trocknungsrate

        Returns:
            BrainDecision mit sleep, irrigation, reasoning und alerts
        """
        target = device_config.get("target_soil_pct", 50)
        delta = device_config.get("irrigation_start_delta", 10)

        # Ungültige Bodenfeuchte abfangen (Sensor-Fehler, fehlende Daten)
        if current_soil is None or not isinstance(current_soil, (int, float)):
            return BrainDecision(
                sleep_duration_s=VERIFICATION_SLEEP_S,
                should_irrigate=False,
                reasoning="Keine gültige Bodenfeuchte — kurzer Sleep zur Verifikation",
                alerts=[{"type": "sensor_error", "message": "Bodenfeuchte-Sensor liefert keine Daten"}],
            )

        reasons = []
        alerts = []

        # Basis-Schwelle (ohne Verdunstung) — für Sleep und Nachtmodus
        base_threshold = soil_threshold(target, delta)

        # --- 1. Basis: Trocknungsraten-Vorhersage ---
        if current_soil < base_threshold:
            # Unter Schwelle: Bewässerung sollte laufen, aber Boden bleibt trocken
            base_sleep = BELOW_THRESHOLD_SLEEP_S
            reasons.append(f"Boden unter Schwelle ({current_soil}% < {base_threshold}%)")
        else:
            drying_rate = self._compute_drying_rate(history or [])
            margin_pct = current_soil - base_threshold

            if drying_rate > 0:
                # Vorhersage: wann erreicht der Boden die Schwelle?
                hours_until_threshold = margin_pct / drying_rate
                base_sleep = hours_until_threshold * DRYING_SAFETY_FACTOR * 3600
                reasons.append(
                    f"Trocknungsrate {drying_rate:.2f}%/h, "
                    f"~{hours_until_threshold:.1f}h bis Schwelle"
                )
            else:
                # Keine Trocknung erkannt oder keine Historie → Fallback
                base_sleep = DEFAULT_BASE_SLEEP_S
                if current_soil >= target:
                    over = current_soil - target
                    base_sleep *= 1.0 + min(over / 20, 1.5)
                    reasons.append(f"Boden feucht ({current_soil}%, Ziel {target}%)")
                else:
                    reasons.append(f"Boden trocknet ({current_soil}%, Ziel {target}%), noch keine Trocknungsrate berechnet")

        sleep_s = base_sleep

        # --- 2. Boden-Trend (wenn vorherige Messung vorhanden) ---
        if previous_soil is not None:
            trend = current_soil - previous_soil
            if trend <= -3:
                sleep_s *= 0.75
                reasons.append(f"Feuchte sinkt schnell ({trend:+d}%)")
            elif trend >= 3:
                sleep_s *= 1.1
                reasons.append(f"Feuchte steigt ({trend:+d}%)")

        # --- 3. Pflanzenart-Multiplikator ---
        sleep_s *= plant_multiplier
        if plant_multiplier != 1.0:
            reasons.append(f"Pflanzenfaktor {plant_multiplier:.2f}x")

        # --- 4. Temperatur + Verdunstung ---
        # ESP32-Sensor hat Vorrang, Wetter-API als Fallback bei Sensor-Ausfall
        effective_temp = current_temp
        effective_rh = current_rh
        if weather_data and is_outdoor:
            if effective_temp is None:
                effective_temp = weather_data.get("temperature")
            if effective_rh is None:
                effective_rh = weather_data.get("humidity")

        evap_adj = _evap_delta(effective_temp, effective_rh)

        # Evaporation: heiß+trocken → kürzer (analog ESP32 offline-Logik)
        # Linear: evap 0 → 1.0x, evap 8 → 0.5x
        if evap_adj > 0:
            sleep_s = int(sleep_s * (16 - evap_adj) / 16)
            reasons.append(f"Verdunstung hoch (evap={evap_adj})")

        # Kälte: Boden trocknet langsamer → seltener prüfen
        if effective_temp is not None and -20 < effective_temp < 5:
            sleep_s *= 1.3
            reasons.append(f"Kalt ({effective_temp:.1f}°C)")

        # --- 5. Wetter-Faktor (nur Outdoor) ---
        rain_expected = False
        if weather_data and is_outdoor:
            rain_1h = weather_data.get("precipitation_next_1h", 0)
            rain_3h = weather_data.get("precipitation_next_3h", 0)

            if rain_3h > 5:
                sleep_s *= 2.0
                rain_expected = True
                reasons.append(f"Starkregen erwartet ({rain_3h:.1f}mm in 3h)")
            elif rain_3h > 2:
                sleep_s *= 1.5
                rain_expected = True
                reasons.append(f"Regen erwartet ({rain_3h:.1f}mm in 3h)")
            elif rain_1h > 0.5:
                sleep_s *= 1.3
                rain_expected = True
                reasons.append(f"Leichter Regen erwartet ({rain_1h:.1f}mm in 1h)")

        # --- 6. Nachtmodus (22:00 - 06:00) ---
        # Fällt die geplante Aufwachzeit in die Nacht, wird auf 06:00 verschoben
        # (Verlängerung auf maximal 12 h), statt nachts ohne Verdunstung erneut zu messen.
        if now_ts is None:
            now_ts = int(time.time())
        wake = datetime.fromtimestamp(now_ts + sleep_s)
        if (wake.hour >= 22 or wake.hour < 6) and current_soil >= base_threshold:
            morning = wake.replace(hour=6, minute=0, second=0, microsecond=0)
            if wake.hour >= 22:
                morning += timedelta(days=1)
            night_sleep = min(int(morning.timestamp()) - now_ts, 43200)
            if night_sleep > sleep_s:
                sleep_s = night_sleep
                reasons.append("Nachtmodus (bis 06:00)")

        # --- 7. Limits ---
        sleep_s = int(max(MIN_SLEEP_S, min(MAX_SLEEP_S, sleep_s)))

        # --- 8. Bewässerungsentscheidung ---
        irr_threshold = irrigation_threshold(target, delta, evap_adj)
        should_irrigate = current_soil < irr_threshold

        # Frost-Sperre: bei ≤0°C nie gießen (Wasser gefriert, Pumpenschaden)
        if should_irrigate and effective_temp is not None and effective_temp <= FROST_TEMP_C:
            should_irrigate = False
            reasons.append(f"Frost-Sperre ({effective_temp:.1f}°C ≤ {FROST_TEMP_C}°C)")
            alerts.append({"type": "frost_lock",
                           "message": f"Bewässerung gesperrt: Frost ({effective_temp:.1f}°C)"})

        # Cooldown prüfen
        cooldown_active = last_irrigated_ts > 0 and (now_ts - last_irrigated_ts) < COOLDOWN_SECONDS
        if cooldown_active and should_irrigate:
            should_irrigate = False
            remaining = COOLDOWN_SECONDS - (now_ts - last_irrigated_ts)
            reasons.append(f"Bewässerungs-Cooldown aktiv (noch {remaining // 60} Minuten)")

        # Regen-Check
        if should_irrigate and rain_expected and is_outdoor:
            should_irrigate = False
            reasons.append("Bewässerung übersprungen (Regen erwartet)")
            alerts.append({"type": "irrigation_skipped_rain",
                           "message": "Bewässerung wegen Regenvorhersage übersprungen"})

        if should_irrigate:
            reasons.append(f"Bewässerung ausgelöst (Boden {current_soil}% < Schwelle {irr_threshold}%)")
            sleep_s = VERIFICATION_SLEEP_S
            reasons.append(f"Verifikation nach Bewässerung → Sleep {VERIFICATION_SLEEP_S // 60} Min")

        # --- 9. Alerts ---
        dry_critical = current_soil < (irr_threshold - 5)
        if dry_critical:
            alerts.append({"type": "dry_critical",
                           "message": f"Boden kritisch trocken ({current_soil}%)"})

        return BrainDecision(
            sleep_duration_s=sleep_s,
            should_irrigate=should_irrigate,
            reasoning="; ".join(reasons),
            alerts=alerts,
        )
