# Prüft, dass Host, Firmware und Dashboard dieselben Formate und Werte verwenden.
# Die Firmware- und Dashboard-Dateien werden dafür direkt gelesen.
import re
import struct
from pathlib import Path

import pytest

from src.ble.parser import MeasurementParser
from src.core import brain
from src.utils import constants

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"
DASHBOARD_JS = Path(__file__).resolve().parents[1] / "static" / "js"

C_TO_STRUCT = {"uint8_t": "B", "uint16_t": "H", "uint32_t": "I", "uint64_t": "Q", "float": "f"}


def read(rel_path):
    return (FIRMWARE / rel_path).read_text(encoding="utf-8")


def config_define(name):
    match = re.search(rf"#define\s+{name}\s+(\d+)", read("main/config.h"))
    assert match, f"{name} fehlt in config.h"
    return int(match.group(1))


def test_measurement_format_matches_struct():
    body = read("main/measurement_types.h").split("{", 1)[1].split("}", 1)[0]
    types = re.findall(r"^\s*(\w+)\s+\w+;", body, flags=re.MULTILINE)
    assert MeasurementParser.FMT == "<" + "".join(C_TO_STRUCT[t] for t in types)
    assert struct.calcsize(MeasurementParser.FMT) == 81


def test_ble_uuids_match():
    firmware_uuids = set()
    for args in re.findall(r"BLE_UUID128_INIT\(([^)]*)\)", read("components/ble/ble_link.c")):
        # NimBLE erwartet die Bytes in umgekehrter Reihenfolge
        h = "".join(f"{int(b, 16):02X}" for b in reversed(args.split(",")))
        firmware_uuids.add(f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}")
    host_uuids = {v for k, v in vars(constants).items() if k.startswith("UUID_")}
    assert firmware_uuids == host_uuids


def test_evaporation_table_matches():
    match = re.search(r"EVAP_TABLE\[3\]\[3\]\s*=\s*\{(.*?)\};", read("main/main.c"), flags=re.DOTALL)
    rows = [[int(v) for v in row.split(",")] for row in re.findall(r"\{([^{}]*)\}", match.group(1))]
    assert rows == brain.EVAP_TABLE


@pytest.mark.parametrize("define,host_value", [
    ("IRR_TARGET_TOLERANCE_PCT", brain.IRR_TARGET_TOLERANCE_PCT),
    ("IRR_THRESHOLD_MIN_PCT", brain.IRR_THRESHOLD_MIN_ABS),
    ("IRR_THRESHOLD_TARGET_FACTOR", round(brain.IRR_THRESHOLD_TARGET_RATIO * 100)),
    ("DEFAULT_TARGET_SOIL_PCT", constants.DEFAULT_TARGET_SOIL),
    ("DEFAULT_IRRIGATION_DELTA", constants.DEFAULT_IRR_DELTA),
])
def test_irrigation_constants_match(define, host_value):
    assert config_define(define) == host_value


def test_device_name_matches():
    assert f'"{constants.DEVICE_NAME}"' in read("main/config.h")


def test_dashboard_threshold_matches():
    app_js = (DASHBOARD_JS / "app.js").read_text(encoding="utf-8")
    for name in ("IRR_THRESHOLD_TARGET_RATIO", "IRR_THRESHOLD_MIN_ABS"):
        match = re.search(rf"{name}:\s*([\d.]+)", app_js)
        assert match, f"{name} fehlt in app.js"
        assert float(match.group(1)) == getattr(brain, name)


@pytest.mark.parametrize("js_file,field", [
    ("settings.js", 'id="set-target"'),
    ("preset_editor.js", 'data-field="target_soil_pct"'),
    ("settings.js", 'id="set-irr-delta"'),
    ("preset_editor.js", 'data-field="irrigation_start_delta"'),
])
def test_dashboard_input_limits_match(js_file, field):
    match = re.search(rf'{field}\s+min="(\d+)"\s+max="(\d+)"', (DASHBOARD_JS / js_file).read_text(encoding="utf-8"))
    assert match, f"Grenzen für {field} fehlen in {js_file}"
    if "delta" in field:
        expected = (constants.IRR_DELTA_MIN, constants.IRR_DELTA_MAX)
    else:
        expected = (constants.TARGET_SOIL_MIN, constants.TARGET_SOIL_MAX)
    assert (int(match.group(1)), int(match.group(2))) == expected
