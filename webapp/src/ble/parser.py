# src/ble/parser.py
# BLE-Messdaten-Parser: entpackt binäre Sensorpakete (struct) in Messwert-Objekte.
import math
import struct
import logging

logger = logging.getLogger("Parser")


class MeasurementParser:
    """
    Parst das measurement_t Struct aus der ESP32-Firmware.
    Layout entspricht measurement_types.h (packed, little-endian).

    Felder:
        uint32_t measurement_id
        float    temp_c
        float    rh_pct
        uint8_t  soil_pct
        uint16_t soil_raw
        uint32_t unix_time
        uint8_t  irrigated
        uint32_t irrigation_ms
        float    battery_voltage
        uint8_t  online
        uint8_t  reset_reason
        uint8_t  target_soil_pct
        uint8_t  irrigation_start_delta
        uint32_t offline_sleep_s
        uint16_t calib_raw_dry
        uint16_t calib_raw_wet
        uint32_t total_wakeups
        float    avg_awake_s
        float    ble_success_pct
        uint32_t total_irrigation_ms
        uint64_t total_awake_ms
        uint32_t last_awake_time_ms
        uint32_t last_sleep_duration_s
        uint32_t uptime_seconds
        uint32_t free_heap_bytes
    """

    FMT = "<IffBHIBIfBBBBIHHIffIQIIII"

    @staticmethod
    def parse(data: bytearray):
        try:
            expected_size = struct.calcsize(MeasurementParser.FMT)
            if len(data) != expected_size:
                logger.error(
                    f"Payload-Größe stimmt nicht! Erwartet {expected_size} Bytes, "
                    f"erhalten {len(data)}"
                )
                return None

            u = struct.unpack(MeasurementParser.FMT, data)

            return {
                # Messwerte (NaN = Sensorfehler → None)
                "measurement_id": u[0],
                "temp": None if math.isnan(u[1]) else round(u[1], 2),
                "rh": None if math.isnan(u[2]) else round(u[2], 2),
                "soil_pct": u[3],
                "soil_raw": u[4],
                "timestamp": u[5],

                # Bewässerung
                "irrigated": bool(u[6]),
                "irrigation_ms": u[7],

                # Status
                "vbat": round(u[8], 3),
                "online": bool(u[9]),
                "reset_reason": u[10],

                # Config-Snapshot
                "target_soil_pct": u[11],
                "irrigation_start_delta": u[12],
                "offline_sleep_s": u[13],
                "calib_dry": u[14],
                "calib_wet": u[15],

                # Statistiken
                "total_wakeups": u[16],
                "avg_awake_s": round(u[17], 3),
                "ble_success_pct": round(u[18], 1),
                "total_irrigation_ms": u[19],

                # Debug
                "total_awake_ms": u[20],
                "last_awake_time_ms": u[21],
                "last_sleep_duration_s": u[22],
                "uptime_seconds": u[23],
                "free_heap_bytes": u[24],
            }
        except Exception as e:
            logger.error(f"Parsing-Fehler: {e}")
            return None
