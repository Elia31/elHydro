/**
 * @file lm393.h
 * @brief Treiber für LM393 Bodenfeuchtesensor (kapazitiv)
 */

#ifndef LM393_H
#define LM393_H

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
    gpio_num_t    do_gpio;     // Digital-Ausgang (Schwellwert), GPIO_NUM_NC = deaktiviert
    int           samples;     // Anzahl Messungen für Mittelwert
} lm393_cfg_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert ADC und optional GPIO (keine Kalibrierung, nur Hardware-Setup)
esp_err_t lm393_init(const lm393_cfg_t* cfg);

// Liest den Sensor aus:
//   raw    - gemittelter ADC-Rohwert
//   do_lvl - Digitalausgang (1 = trocken, 0 = feucht), NULL wenn nicht benötigt
esp_err_t lm393_read_raw(int* raw, int* do_lvl);

// Gibt das interne ADC-Handle zurück (für gemeinsame Nutzung, z.B. Batteriemessung)
adc_oneshot_unit_handle_t lm393_get_adc_handle(void);

// Gibt Ressourcen frei
void lm393_deinit(void);

#endif // LM393_H