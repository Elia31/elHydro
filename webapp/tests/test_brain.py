# Tests für die Schlaf- und Bewässerungsentscheidung (src/core/brain.py)
from datetime import datetime

import pytest

from src.core.brain import (
    MAX_SLEEP_S,
    MIN_SLEEP_S,
    VERIFICATION_SLEEP_S,
    Brain,
)

# Ortszeit, weil der Nachtmodus mit der lokalen Uhrzeit rechnet
NOON = int(datetime(2026, 6, 15, 12, 0).timestamp())
EVENING = int(datetime(2026, 6, 15, 20, 0).timestamp())

# Ziel 45 %, Delta 10 % → Schwelle 35 %. 10 °C bei 80 % Luftfeuchte ergibt
# keinen Verdunstungszuschlag und keinen Kälte-Faktor.
CONFIG = {"target_soil_pct": 45, "irrigation_start_delta": 10}


def decide(**kwargs):
    args = {
        "device_config": CONFIG,
        "current_soil": 45,
        "current_temp": 10.0,
        "current_rh": 80,
        "now_ts": NOON,
    }
    args.update(kwargs)
    return Brain().decide(**args)


def alert_types(decision):
    return [a["type"] for a in decision.alerts]


def test_irrigates_below_threshold():
    d = decide(current_soil=30)
    assert d.should_irrigate
    assert d.sleep_duration_s == VERIFICATION_SLEEP_S


def test_no_irrigation_above_threshold():
    assert not decide(current_soil=40).should_irrigate


def test_evaporation_raises_threshold():
    # 32 °C bei 30 % Luftfeuchte: Zuschlag 8 → Schwelle 43 %
    assert decide(current_soil=40, current_temp=32.0, current_rh=30).should_irrigate


def test_threshold_stays_below_target():
    # Delta 1 plus Zuschlag 8 läge über dem Ziel, die Schwelle bleibt bei Ziel - 2 %
    d = decide(device_config={"target_soil_pct": 45, "irrigation_start_delta": 1},
               current_soil=44, current_temp=32.0, current_rh=30)
    assert not d.should_irrigate


def test_frost_blocks_irrigation():
    d = decide(current_soil=20, current_temp=-2.0)
    assert not d.should_irrigate
    assert "frost_lock" in alert_types(d)


def test_cooldown_blocks_irrigation():
    assert not decide(current_soil=20, last_irrigated_ts=NOON - 600).should_irrigate


def test_rain_blocks_irrigation_outdoor_only():
    weather = {"precipitation_next_1h": 0, "precipitation_next_3h": 6}
    outdoor = decide(current_soil=20, is_outdoor=True, weather_data=weather)
    assert not outdoor.should_irrigate
    assert "irrigation_skipped_rain" in alert_types(outdoor)
    assert decide(current_soil=20, is_outdoor=False, weather_data=weather).should_irrigate


def test_missing_soil_value():
    d = decide(current_soil=None)
    assert not d.should_irrigate
    assert "sensor_error" in alert_types(d)


def test_sleep_from_drying_rate():
    # 2 %/h Trocknung, 56 % → noch 21 % bis zur Schwelle = 10,5 h, davon 70 %
    history = [
        {"timestamp": NOON - 7200, "soil_pct": 60},
        {"timestamp": NOON - 3600, "soil_pct": 58},
    ]
    assert decide(current_soil=56, history=history).sleep_duration_s == int(10.5 * 0.7 * 3600)


def test_night_mode_wakes_at_six():
    d = decide(current_soil=80, now_ts=EVENING)
    assert datetime.fromtimestamp(EVENING + d.sleep_duration_s).hour == 6


@pytest.mark.parametrize("soil", [36, 50, 75, 100])
@pytest.mark.parametrize("temp,rh", [(10.0, 80), (35.0, 20), (-10.0, 90)])
def test_sleep_within_limits(soil, temp, rh):
    d = decide(current_soil=soil, current_temp=temp, current_rh=rh)
    assert MIN_SLEEP_S <= d.sleep_duration_s <= MAX_SLEEP_S
