/**
 * @file display_ui.h
 * @brief UI-Komponenten für das E-Paper Display
 *
 * Stellt fertige Screens bereit: Normal-Anzeige, Setup,
 * Kalibrierung und Werksreset.
 */

#ifndef DISPLAY_UI_H
#define DISPLAY_UI_H

#include <stdint.h>

#include "display_hal.h"
#include "esp_err.h"

// ============================================================================
// Datenstruktur für Normal-Screen
// ============================================================================

typedef struct
{
    // Messwerte
    float temp_c;
    float rh_pct;
    int   soil_pct;
    int   soil_raw;

    // Konfiguration
    int target_soil_pct;
    int calib_raw_dry;
    int calib_raw_wet;

    // Zeitstempel
    uint32_t last_measurement_unix;
    uint32_t next_measurement_unix;
    uint32_t sleep_duration_s;
    bool     time_valid;

    // Status
    int      buffer_count;
    float    battery_voltage;
    bool     ble_connected;
    uint32_t measurement_id;
    uint32_t last_irrigation_ms;

    // Statistiken
    uint32_t total_wakeups;
    float    avg_awake_s;
    float    ble_success_pct;
} display_ui_data_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert das Display (Wrapper für display_hal_init)
esp_err_t display_ui_init(const display_hal_config_t* cfg);

// Hauptbildschirm mit allen Messwerten und Status
void display_ui_show_normal_screen(const display_ui_data_t* data);

// Ersteinrichtungs-Bildschirm (wartet auf Bluetooth-Verbindung)
void display_ui_show_setup_screen(void);

// Kalibrierung Schritt 1: Sensor trocknen und in Luft halten
void display_ui_show_calibration_step1(void);

// Kalibrierung Schritt 2: Sensor in Wasser tauchen
void display_ui_show_calibration_step2(void);

// Kalibrierung erfolgreich abgeschlossen
void display_ui_show_calibration_success(int raw_dry, int raw_wet);

// Kalibrierung wegen Timeout abgebrochen
void display_ui_show_calibration_timeout(void);

// Kalibrierung verworfen (Trocken-/Nasswert unplausibel)
void display_ui_show_calibration_failed(int raw_dry, int raw_wet);

// Werksreset-Bestätigung anzeigen
void display_ui_show_factory_reset_confirm(void);

// Werksreset durchgeführt
void display_ui_show_factory_reset_done(void);

#endif // DISPLAY_UI_H