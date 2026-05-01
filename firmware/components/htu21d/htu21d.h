/**
 * @file htu21d.h
 * @brief Treiber für HTU21D Temperatur- und Feuchtigkeitssensor
 */

#ifndef HTU21D_H
#define HTU21D_H

#include "esp_err.h"

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert den Sensor und prüft ob er antwortet
esp_err_t htu21d_init(void);

// Liest die Temperatur in °C
esp_err_t htu21d_read_temperature(float* temp_c);

// Liest die relative Luftfeuchtigkeit in %
esp_err_t htu21d_read_humidity(float* rh_pct);

#endif // HTU21D_H