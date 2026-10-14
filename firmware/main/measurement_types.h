/**
 * @file measurement_types.h
 * @brief Einheitliches Datenformat für Messungen
 *
 * Dieses Struct wird verwendet für:
 * - NVS-Speicherung (Offline-Buffer)
 * - BLE-Übertragung (Wire-Format)
 * - Interne Verarbeitung
 *
 * Optimierung: Vermeidet mehrfaches Kopieren der Messdaten
 */

#ifndef MEASUREMENT_TYPES_H
#define MEASUREMENT_TYPES_H

#include <stdint.h>

typedef struct __attribute__((packed))
{
    // Messwerte
    uint32_t measurement_id;
    float    temp_c;
    float    rh_pct;
    uint8_t  soil_pct;
    uint16_t soil_raw;
    uint32_t unix_time;

    // Bewässerung
    uint8_t  irrigated;
    uint32_t irrigation_ms;

    // Status
    float   battery_voltage;
    uint8_t online; // Wird erst beim Senden gesetzt
    uint8_t reset_reason;

    // Konfiguration (zum Zeitpunkt der Messung)
    uint8_t  target_soil_pct;
    uint8_t  irrigation_start_delta;
    uint32_t offline_sleep_s;
    uint16_t calib_raw_dry;
    uint16_t calib_raw_wet;

    // Statistiken
    uint32_t total_wakeups;
    float    avg_awake_s;
    float    ble_success_pct;
    uint32_t total_irrigation_ms;

    // Debug-Informationen
    uint64_t total_awake_ms;
    uint32_t last_awake_time_ms;
    uint32_t last_sleep_duration_s;
    uint32_t uptime_seconds;
    uint32_t free_heap_bytes;

    // Gegossen, aber die Bodenfeuchte ist nicht gestiegen (Tank leer?). Steht am Ende,
    // damit ältere 80-Byte-Einträge im NVS-Puffer weiterhin gelesen werden können.
    uint8_t pump_dry;
} measurement_t;

#endif // MEASUREMENT_TYPES_H