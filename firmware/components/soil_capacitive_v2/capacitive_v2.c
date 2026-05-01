/**
 * @file capacitive_v2.c
 * @brief Treiber für kapazitiven Bodenfeuchtesensor v2.0.0
 *
 * Direkter ADC-Anschluss ohne Komparator-IC.
 * Liest analogen Feuchtigkeitswert über ADC mit Mittelwertbildung.
 */

#include "capacitive_v2.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char* TAG = "CAP_V2";

// ============================================================================
// Interner Zustand
// ============================================================================

static bool                      s_initialized = false;
static capacitive_v2_cfg_t       s_cfg;
static adc_oneshot_unit_handle_t s_adc = NULL;

// ============================================================================
// Hilfsfunktionen
// ============================================================================

static int adc_read_averaged(adc_oneshot_unit_handle_t handle, adc_channel_t channel, int num_samples)
{
    if (num_samples <= 0)
    {
        num_samples = 1;
    }

    int value = 0;
    for (int i = 0; i < 3; i++)
    {
        adc_oneshot_read(handle, channel, &value);
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    int sum   = 0;
    int count = 0;

    for (int i = 0; i < num_samples; i++)
    {
        if (adc_oneshot_read(handle, channel, &value) == ESP_OK)
        {
            sum += value;
            count++;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }

    return (count > 0) ? (sum / count) : 0;
}

// ============================================================================
// Initialisierung
// ============================================================================

esp_err_t capacitive_v2_init(const capacitive_v2_cfg_t* cfg)
{
    if (!cfg)
    {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_initialized)
    {
        return ESP_OK;
    }

    s_cfg = *cfg;
    if (s_cfg.samples <= 0)
    {
        s_cfg.samples = 8;
    }

    // ADC konfigurieren
    adc_oneshot_unit_init_cfg_t unit_cfg = { .unit_id = s_cfg.adc_unit };
    esp_err_t                   err      = adc_oneshot_new_unit(&unit_cfg, &s_adc);
    if (err != ESP_OK)
    {
        return err;
    }

    adc_oneshot_chan_cfg_t chan_cfg = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
    err                             = adc_oneshot_config_channel(s_adc, s_cfg.adc_channel, &chan_cfg);
    if (err != ESP_OK)
    {
        adc_oneshot_del_unit(s_adc);
        s_adc = NULL;
        return err;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "Init OK: ADC%d CH%d, Samples=%d", (int) s_cfg.adc_unit, (int) s_cfg.adc_channel, s_cfg.samples);

    return ESP_OK;
}

// ============================================================================
// Messung
// ============================================================================

esp_err_t capacitive_v2_read_raw(int* raw, int* do_lvl)
{
    if (!s_initialized)
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (raw)
    {
        *raw = adc_read_averaged(s_adc, s_cfg.adc_channel, s_cfg.samples);
    }

    if (do_lvl)
    {
        *do_lvl = -1; // Kein Digitalausgang
    }

    return ESP_OK;
}

adc_oneshot_unit_handle_t capacitive_v2_get_adc_handle(void)
{
    return s_adc;
}

// ============================================================================
// Deinitialisierung
// ============================================================================

void capacitive_v2_deinit(void)
{
    if (!s_initialized)
    {
        return;
    }

    if (s_adc)
    {
        adc_oneshot_del_unit(s_adc);
        s_adc = NULL;
    }

    s_initialized = false;
}
