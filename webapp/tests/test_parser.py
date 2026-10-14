# Tests für das Entpacken der BLE-Messpakete (src/ble/parser.py)
import struct

from src.ble.parser import MeasurementParser


def make_payload(**overrides):
    # Reihenfolge wie in firmware/main/measurement_types.h
    fields = {
        "measurement_id": 7, "temp_c": 21.5, "rh_pct": 55.25, "soil_pct": 42,
        "soil_raw": 1800, "unix_time": 1_790_000_000, "irrigated": 1, "irrigation_ms": 3000,
        "battery_voltage": 3.95, "online": 1, "reset_reason": 8, "target_soil_pct": 45,
        "irrigation_start_delta": 10, "offline_sleep_s": 14400, "calib_raw_dry": 2600,
        "calib_raw_wet": 800, "total_wakeups": 120, "avg_awake_s": 2.5,
        "ble_success_pct": 98.0, "total_irrigation_ms": 60000, "total_awake_ms": 300000,
        "last_awake_time_ms": 2400, "last_sleep_duration_s": 3600,
        "uptime_seconds": 500000, "free_heap_bytes": 200000, "pump_dry": 0,
    }
    fields.update(overrides)
    return struct.pack(MeasurementParser.FMT, *fields.values())


def test_parse_fields():
    m = MeasurementParser.parse(make_payload())
    assert m["measurement_id"] == 7
    assert m["temp"] == 21.5
    assert m["rh"] == 55.25
    assert m["soil_pct"] == 42
    assert m["timestamp"] == 1_790_000_000
    assert m["irrigated"] is True
    assert m["vbat"] == 3.95
    assert m["online"] is True
    assert m["calib_dry"] == 2600
    assert m["calib_wet"] == 800
    assert m["total_awake_ms"] == 300000
    assert m["free_heap_bytes"] == 200000
    assert m["pump_dry"] is False
    assert MeasurementParser.parse(make_payload(pump_dry=1))["pump_dry"] is True


def test_nan_becomes_none():
    m = MeasurementParser.parse(make_payload(temp_c=float("nan"), rh_pct=float("nan")))
    assert m["temp"] is None
    assert m["rh"] is None


def test_wrong_size_is_rejected():
    payload = make_payload()
    assert MeasurementParser.parse(payload[:-2]) is None
    assert MeasurementParser.parse(payload + b"\x00") is None


def test_old_firmware_without_pump_dry():
    # Firmware vor der Trockenlauf-Erkennung sendet das Struct ohne das letzte Byte
    m = MeasurementParser.parse(make_payload()[:-1])
    assert m["soil_pct"] == 42
    assert m["pump_dry"] is False
