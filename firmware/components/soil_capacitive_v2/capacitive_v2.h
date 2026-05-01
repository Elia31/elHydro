/**
 * @file capacitive_v2.h
 * @brief Treiber für kapazitiven Bodenfeuchtesensor v2.0.0
 *
 * Direkter ADC-Anschluss ohne Komparator-IC.
 * API-kompatibel zum LM393-Treiber für einfachen Austausch.
 */

#ifndef CAPACITIVE_V2_H
#define CAPACITIVE_V2_H

#include <stdbool.h>

#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"

// ============================================================================
// Konfiguration
// ============================================================================

typedef struct
{
    adc_unit_t    adc_unit;    // ADC-Einheit (z.B. ADC_UNIT_1)
    adc_channel_t adc_channel; // ADC-Kanal für Analogwert
    gpio_num_t    do_gpio;     // Nicht verwendet (GPIO_NUM_NC), für API-Kompatibilität
    int           samples;     // Anzahl Messungen für Mittelwert
} capacitive_v2_cfg_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert ADC (keine Kalibrierung, nur Hardware-Setup)
esp_err_t capacitive_v2_init(const capacitive_v2_cfg_t* cfg);

// Liest den Sensor aus:
//   raw    - gemittelter ADC-Rohwert
//   do_lvl - immer -1 (kein Digitalausgang), für API-Kompatibilität
esp_err_t capacitive_v2_read_raw(int* raw, int* do_lvl);

// Gibt das interne ADC-Handle zurück (für gemeinsame Nutzung, z.B. Batteriemessung)
adc_oneshot_unit_handle_t capacitive_v2_get_adc_handle(void);

// Gibt Ressourcen frei
void capacitive_v2_deinit(void);

#endif // CAPACITIVE_V2_H
