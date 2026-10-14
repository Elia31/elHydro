/**
 * @file main.c
 * @brief elHydro - Bodenfeuchtigkeits-Überwachungssystem
 *
 * Hauptprogramm mit Finite State Machine für den Betriebsablauf:
 * INIT → FIRST_SETUP/MEASURE → BLE → DISPLAY → SLEEP
 *
 * Das System verbringt 99% der Zeit im Deep Sleep und wacht
 * periodisch auf um Sensoren auszulesen und Daten zu übertragen.
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_err.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "nvs.h"
#include "nvs_flash.h"

// Konfiguration
#include "config.h"
#include "pins.h"
#include "measurement_types.h"

// Hardware-Treiber
#include "display_hal.h"
#include "display_ui.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "htu21d.h"
#include "i2c_utils.h"
// Sensor-Abstraktion: Je nach config.h wird LM393 oder kapazitiver Sensor genutzt
#if USE_LM393_SENSOR
    #include "lm393.h"
    #define soil_init           lm393_init
    #define soil_read_raw       lm393_read_raw
    #define soil_get_adc_handle lm393_get_adc_handle
typedef lm393_cfg_t soil_cfg_t;
#elif USE_CAPACITIVE_V2_SENSOR
    #include "capacitive_v2.h"
    #define soil_init           capacitive_v2_init
    #define soil_read_raw       capacitive_v2_read_raw
    #define soil_get_adc_handle capacitive_v2_get_adc_handle
typedef capacitive_v2_cfg_t soil_cfg_t;
#endif

// Bluetooth LE
#include "ble_link.h"

// Energieverwaltung
#include "esp_pm.h"

static const char* TAG = "MAIN";

// ============================================================================
// Persistente Datenstrukturen
// ============================================================================

// Benutzer-Konfiguration (in NVS gespeichert)
typedef struct
{
    uint8_t  target_soil_pct;
    uint8_t  irrigation_start_delta;
    uint32_t offline_sleep_s;
} app_config_t;

// Sensor-Kalibrierung (in NVS gespeichert)
typedef struct
{
    uint16_t raw_dry;
    uint16_t raw_wet;
} app_calib_t;

// System-Zustand (in NVS gespeichert)
typedef struct
{
    uint32_t measurement_id;
    uint32_t reset_counter;
    bool     initial_setup_done;
} app_state_t;

// Statistiken (in NVS gespeichert)
typedef struct
{
    uint32_t total_wakeups;
    uint64_t total_awake_ms;
    uint32_t ble_attempts;
    uint32_t ble_success_count;
    uint32_t last_sleep_duration_s;
    uint32_t last_cycle_awake_ms;
    uint32_t total_irrigation_ms;
} app_stats_t;

// ============================================================================
// FSM-Definitionen
// ============================================================================

typedef enum
{
    STATE_INIT,
    STATE_FIRST_SETUP,
    STATE_MEASURE,
    STATE_BLE_SEND_RECEIVE,
    STATE_IRRIGATION,
    STATE_CALIBRATION,
    STATE_UPDATE_DISPLAY,
    STATE_FACTORY_RESET,
    STATE_SLEEP,
    STATE_ERROR
} system_state_t;

typedef struct
{
    system_state_t state;

    // Aktuelle Messwerte
    float    last_temp;
    float    last_rh;
    uint8_t  last_soil_pct;
    uint16_t last_soil_raw;
    float    last_vbat;

    // Bewässerung
    bool     irrigated;       // in DIESEM Wake-Zyklus wurde gegossen?
    uint32_t irrigation_ms;   // gesamte Pumpenlaufzeit in diesem Zyklus (ms)
    bool     should_irrigate; // soll in diesem Zyklus gegossen werden?
    bool     pump_dry;        // gegossen, aber Boden nicht feuchter geworden (Tank leer?)

    // BLE-Status
    bool ble_connected;

    // Sleep-Konfiguration
    uint32_t sleep_duration_s;

} fsm_context_t;

// ============================================================================
// Globale Variablen
// ============================================================================

// Persistente Daten
static app_config_t g_config;
static app_calib_t  g_calib;
static app_state_t  g_state;
static app_stats_t  g_stats;

// FSM-Kontext
static fsm_context_t g_fsm = { 0 };

// Flags
static bool g_factory_reset_requested = false;
static bool g_calibration_requested   = false;

// Zeitmessung für Wach-Dauer
static uint64_t g_boot_time_us = 0;
// Zeitmessung für State-Dauer
static uint64_t s_state_enter_us = 0;
// Summe der pro State verbrachten Zeit (ms), Reset durch Deep Sleep
#define FSM_STATE_COUNT 10
static uint32_t s_cycle_state_ms[FSM_STATE_COUNT] = { 0 };

// Ring-Buffer Metadaten
static int32_t s_buf_head  = 0;
static int32_t s_buf_count = 0;

// Aktuelle Messung im RAM
static measurement_t g_current_meas;
static bool          g_current_meas_valid = false;

// Power Management Lock
static esp_pm_lock_handle_t s_pm_lock = NULL;

// Display beim Start erfolgreich initialisiert? (sonst Betrieb ohne Anzeige)
static bool s_display_ok = false;

// ============================================================================
// RTC-Daten (überleben Deep Sleep)
// ============================================================================

RTC_DATA_ATTR static uint64_t s_rtc_epoch_base_s    = 0;
RTC_DATA_ATTR static uint8_t  s_rtc_time_valid      = 0;
RTC_DATA_ATTR static uint32_t s_rtc_sync_count      = 0;
RTC_DATA_ATTR static int32_t  s_rtc_last_drift_s    = 0;
RTC_DATA_ATTR static float    s_rtc_drift_ppm       = 0.0f; // Gemessene Drift-Rate in ppm
RTC_DATA_ATTR static uint64_t s_rtc_last_sync_rtc_s = 0;    // RTC-Counter bei letztem Sync
RTC_DATA_ATTR static uint8_t  s_rtc_setup_retry     = 0;    // Schläft nach Setup-Timeout (Setup-Bildschirm steht noch)

// ============================================================================
// RTC-Zeit Funktionen
// ============================================================================

extern uint64_t        esp_rtc_get_time_us(void);
static inline uint64_t rtc_now_us(void)
{
    return esp_rtc_get_time_us();
}

static inline uint64_t rtc_now_s(void)
{
    return rtc_now_us() / 1000000ULL;
}

static inline bool time_is_valid(void)
{
    return s_rtc_time_valid == 1;
}

static uint64_t time_now_unix_s(void)
{
    if (!time_is_valid())
    {
        return 0;
    }
    uint64_t raw_time = s_rtc_epoch_base_s + rtc_now_s();

    // Drift-Kompensation anwenden falls verfügbar
    if (s_rtc_drift_ppm != 0.0f && s_rtc_last_sync_rtc_s > 0)
    {
        uint64_t elapsed    = rtc_now_s() - s_rtc_last_sync_rtc_s;
        int64_t  correction = (int64_t) ((float) elapsed * s_rtc_drift_ppm / 1000000.0f);
        raw_time            = (uint64_t) ((int64_t) raw_time + correction);
    }

    return raw_time;
}

static void time_sync_from_host(uint32_t unix_time_now_s)
{
    // Drift berechnen falls bereits synchronisiert
    if (s_rtc_time_valid == 1)
    {
        uint64_t predicted = s_rtc_epoch_base_s + rtc_now_s();
        s_rtc_last_drift_s = (int32_t) ((int64_t) unix_time_now_s - (int64_t) predicted);
        ESP_LOGI(TAG, "Zeit-Drift: %ld s", (long) s_rtc_last_drift_s);

        // Drift-Rate (ppm) berechnen falls genug Zeit vergangen
        if (s_rtc_last_sync_rtc_s > 0)
        {
            uint64_t rtc_elapsed = rtc_now_s() - s_rtc_last_sync_rtc_s;
            if (rtc_elapsed > 60)
            { // Mindestens 1 Minute zwischen Syncs
                float new_ppm = (float) s_rtc_last_drift_s / (float) rtc_elapsed * 1000000.0f;
                // Gleitender Durchschnitt mit vorherigem Wert
                if (s_rtc_sync_count > 1 && s_rtc_drift_ppm != 0.0f)
                {
                    s_rtc_drift_ppm = s_rtc_drift_ppm * 0.3f + new_ppm * 0.7f;
                }
                else
                {
                    s_rtc_drift_ppm = new_ppm;
                }
                ESP_LOGI(TAG, "Drift-Rate: %.1f ppm (elapsed=%llu s)", s_rtc_drift_ppm, (unsigned long long) rtc_elapsed);
            }
        }
    }

    // Neue Basis setzen
    s_rtc_last_sync_rtc_s = rtc_now_s();
    s_rtc_epoch_base_s    = (uint64_t) unix_time_now_s - s_rtc_last_sync_rtc_s;
    s_rtc_time_valid      = 1;
    s_rtc_sync_count++;

    ESP_LOGI(TAG, "Zeit synchronisiert: Base=%llu, Sync #%lu", (unsigned long long) s_rtc_epoch_base_s, (unsigned long) s_rtc_sync_count);
}

// ============================================================================
// Hilfsfunktionen
// ============================================================================

static inline int32_t clamp_0_100(int32_t value)
{
    if (value < 0)
        return 0;
    if (value > 100)
        return 100;
    return value;
}

static inline uint32_t clamp_u32(uint32_t value, uint32_t min, uint32_t max)
{
    if (value < min)
        return min;
    if (value > max)
        return max;
    return value;
}

// Steuerwerte vom Host auf gültige Bereiche begrenzen
static void validate_control(ble_link_control_t* ctrl)
{
    if (ctrl->target_soil_pct > 100)
        ctrl->target_soil_pct = 100;
    if (ctrl->irrigation_start_delta > 100)
        ctrl->irrigation_start_delta = 100;
    if (ctrl->offline_sleep_s == 0)
        ctrl->offline_sleep_s = DEFAULT_OFFLINE_SLEEP_S;
    if (ctrl->sleep_seconds == 0)
        ctrl->sleep_seconds = DEFAULT_OFFLINE_SLEEP_S;

    ctrl->offline_sleep_s = clamp_u32(ctrl->offline_sleep_s, OFFLINE_SLEEP_MIN_S, OFFLINE_SLEEP_MAX_S);
    ctrl->sleep_seconds   = clamp_u32(ctrl->sleep_seconds, SLEEP_MIN_S, SLEEP_MAX_S);
}

static int moisture_pct_from_raw(int raw)
{
    int span = g_calib.raw_dry - g_calib.raw_wet;
    if (span <= 0)
    {
        return 0;
    }
    int pct = (g_calib.raw_dry - raw) * 100 / span;
    return clamp_0_100(pct);
}

// ============================================================================
// Power Management Initialisierung
// ============================================================================

static void sys_init_power_management(void)
{
    esp_pm_config_t pm_config = { .max_freq_mhz       = 160, // Maximaltakt (Standard bei ESP32-C6)
                                  .min_freq_mhz       = 40,  // Minimaltakt im Leerlauf (spart Strom)
                                  .light_sleep_enable = false };

    esp_err_t err = esp_pm_configure(&pm_config);
    if (err != ESP_OK)
    {
        ESP_LOGW(TAG, "PM Init fehlgeschlagen: %d", err);
        return;
    }

    esp_pm_lock_create(ESP_PM_CPU_FREQ_MAX, 0, "adc_lock", &s_pm_lock);

    ESP_LOGI(TAG, "Power Management aktiviert (DFS)");
}

// ============================================================================
// NVS-Funktionen: Konfiguration
// ============================================================================

static void nvs_save_config(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_APP, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_set_blob(handle, NVS_KEY_BLOB_CONFIG, &g_config, sizeof(app_config_t));
        nvs_commit(handle);
        nvs_close(handle);
    }
}

// ============================================================================
// NVS-Funktionen: Kalibrierung
// ============================================================================

static void nvs_save_calib(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_APP, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_set_blob(handle, NVS_KEY_BLOB_CALIB, &g_calib, sizeof(app_calib_t));
        nvs_commit(handle);
        nvs_close(handle);
    }
}

// ============================================================================
// NVS-Funktionen: System-Zustand
// ============================================================================

static void nvs_save_state(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_APP, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_set_blob(handle, NVS_KEY_BLOB_STATE, &g_state, sizeof(app_state_t));
        nvs_commit(handle);
        nvs_close(handle);
    }
}

// ============================================================================
// NVS-Funktionen: Statistiken
// ============================================================================

static void nvs_save_stats(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_APP, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_set_blob(handle, NVS_KEY_BLOB_STATS, &g_stats, sizeof(app_stats_t));
        nvs_commit(handle);
        nvs_close(handle);
    }
}

// ============================================================================
// NVS-Funktionen: Alle laden
// ============================================================================

static void load_all_persistent_data(void)
{
    g_config.target_soil_pct        = DEFAULT_TARGET_SOIL_PCT;
    g_config.irrigation_start_delta = DEFAULT_IRRIGATION_DELTA;
    g_config.offline_sleep_s        = DEFAULT_OFFLINE_SLEEP_S;
    g_calib.raw_dry                 = DEFAULT_CALIB_RAW_DRY;
    g_calib.raw_wet                 = DEFAULT_CALIB_RAW_WET;
    memset(&g_state, 0, sizeof(g_state));
    memset(&g_stats, 0, sizeof(g_stats));

    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_APP, NVS_READONLY, &handle) == ESP_OK)
    {
        size_t size;

        esp_err_t err;

        size = sizeof(app_config_t);
        err  = nvs_get_blob(handle, NVS_KEY_BLOB_CONFIG, &g_config, &size);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND)
        {
            ESP_LOGW(TAG, "NVS load config: %s", esp_err_to_name(err));
        }

        size = sizeof(app_calib_t);
        err  = nvs_get_blob(handle, NVS_KEY_BLOB_CALIB, &g_calib, &size);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND)
        {
            ESP_LOGW(TAG, "NVS load calib: %s", esp_err_to_name(err));
        }

        size = sizeof(app_state_t);
        err  = nvs_get_blob(handle, NVS_KEY_BLOB_STATE, &g_state, &size);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND)
        {
            ESP_LOGW(TAG, "NVS load state: %s", esp_err_to_name(err));
        }

        size = sizeof(app_stats_t);
        err  = nvs_get_blob(handle, NVS_KEY_BLOB_STATS, &g_stats, &size);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND)
        {
            ESP_LOGW(TAG, "NVS load stats: %s", esp_err_to_name(err));
        }

        nvs_close(handle);
    }
}

// ============================================================================
// Ring-Buffer für Offline-Messungen
// ============================================================================

static void buf_load_meta(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_BUF, NVS_READONLY, &handle) == ESP_OK)
    {
        nvs_get_i32(handle, "head", &s_buf_head);
        nvs_get_i32(handle, "cnt", &s_buf_count);
        nvs_close(handle);
    }

    // Plausibilitätsprüfung
    if (s_buf_head < 0 || s_buf_head >= MAX_BUFFER_ENTRIES)
    {
        s_buf_head = 0;
    }
    if (s_buf_count < 0 || s_buf_count > MAX_BUFFER_ENTRIES)
    {
        s_buf_count = 0;
    }
}

static void buf_save_meta(void)
{
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_BUF, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_set_i32(handle, "head", s_buf_head);
        nvs_set_i32(handle, "cnt", s_buf_count);
        nvs_commit(handle);
        nvs_close(handle);
    }
}

static void buf_push(const measurement_t* record)
{
    char key[8];
    snprintf(key, sizeof(key), "m%04d", (int) s_buf_head);

    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_BUF, NVS_READWRITE, &handle) == ESP_OK)
    {
        esp_err_t err = nvs_set_blob(handle, key, record, sizeof(*record));
        if (err == ESP_OK)
        {
            err = nvs_commit(handle);
        }
        nvs_close(handle);

        if (err != ESP_OK)
        {
            ESP_LOGE(TAG, "Buffer: Speichern fehlgeschlagen (%s)", esp_err_to_name(err));
            return;
        }

        s_buf_head = (s_buf_head + 1) % MAX_BUFFER_ENTRIES;
        if (s_buf_count < MAX_BUFFER_ENTRIES)
        {
            s_buf_count++;
        }

        buf_save_meta();
        ESP_LOGI(TAG, "Buffer: Eintrag hinzugefügt, Count=%d", (int) s_buf_count);
    }
}

static int buf_flush_and_send(void)
{
    if (s_buf_count == 0)
    {
        return 0;
    }

    // Ältesten Eintrag berechnen
    int oldest   = (s_buf_head - s_buf_count + MAX_BUFFER_ENTRIES) % MAX_BUFFER_ENTRIES;
    int sent     = 0;
    int consumed = 0; // gesendete + unlesbare Einträge (vom ältesten an gezählt)

    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_BUF, NVS_READWRITE, &handle) != ESP_OK)
    {
        return 0;
    }

    for (int i = 0; i < s_buf_count; i++)
    {
        int  idx = (oldest + i) % MAX_BUFFER_ENTRIES;
        char key[8];
        snprintf(key, sizeof(key), "m%04d", idx);

        measurement_t record = { 0 };
        size_t        size   = sizeof(record);

        if (nvs_get_blob(handle, key, &record, &size) != ESP_OK)
        {
            // Fehlender/defekter Eintrag: überspringen, aber als verbraucht zählen,
            // sonst bleibt er als Phantom-Eintrag dauerhaft im Zähler stehen
            ESP_LOGW(TAG, "Buffer: Eintrag idx=%d nicht lesbar, überspringe", idx);
            consumed++;
            continue;
        }

        // Erst löschen, wenn der Host den Empfang bestätigt hat. Unbestätigte Einträge
        // bleiben im Puffer und werden beim nächsten Kontakt erneut gesendet.
        if (ble_link_send_measurement(&record) == ESP_OK)
        {
            sent++;
            consumed++;
            nvs_erase_key(handle, key);
        }
        else
        {
            ESP_LOGW(TAG, "BLE: Senden fehlgeschlagen bei idx=%d", idx);
            break;
        }
    }

    nvs_commit(handle);
    nvs_close(handle);

    // Zähler aktualisieren
    s_buf_count = s_buf_count - consumed;
    if (s_buf_count < 0)
    {
        s_buf_count = 0;
    }
    buf_save_meta();

    ESP_LOGI(TAG, "Buffer: %d gesendet, %d verbleibend", sent, (int) s_buf_count);
    return sent;
}

static void store_measurement_if_needed(void)
{
    if (!g_current_meas_valid)
    {
        return;
    }

    ESP_LOGW(TAG, "Messung nicht gesendet -> Speichere in NVS Buffer");
    g_current_meas.online = 0;
    buf_push(&g_current_meas);
    g_current_meas_valid = false;
}

// ============================================================================
// GPIO Power Control
// ============================================================================

static void gpio_power(gpio_num_t pin, bool on)
{
    static bool pins_initialized[GPIO_NUM_MAX] = { false };

    if (!pins_initialized[pin])
    {
        gpio_reset_pin(pin);
        gpio_set_direction(pin, GPIO_MODE_OUTPUT);
        pins_initialized[pin] = true;
    }

    gpio_set_level(pin, on ? 1 : 0);
}

static void pump_set(bool on)
{
    gpio_power(PUMP_GPIO, on ? PUMP_ACTIVE_LEVEL : !PUMP_ACTIVE_LEVEL);
}

// ============================================================================
// Sensor-Funktionen
// ============================================================================

static int read_soil_raw(void)
{
    int raw     = 0;
    int digital = 0;
    soil_read_raw(&raw, &digital);
    return raw;
}

static float read_battery_voltage(void)
{
#if ENABLE_BATTERY_ADC
    static bool              s_vbat_configured = false;
    static adc_cali_handle_t s_vbat_cali       = NULL;

    adc_oneshot_unit_handle_t adc = soil_get_adc_handle();
    if (!adc)
    {
        return 0.0f;
    }

    if (!s_vbat_configured)
    {
        adc_oneshot_chan_cfg_t chan_cfg = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
        if (adc_oneshot_config_channel(adc, VBAT_ADC_CHANNEL, &chan_cfg) != ESP_OK)
        {
            return 0.0f;
        }

        // ADC-Kalibrierung initialisieren für genaue mV-Werte
        adc_cali_curve_fitting_config_t cali_cfg = {
            .unit_id  = VBAT_ADC_UNIT,
            .atten    = ADC_ATTEN_DB_12,
            .bitwidth = ADC_BITWIDTH_DEFAULT,
        };
        if (adc_cali_create_scheme_curve_fitting(&cali_cfg, &s_vbat_cali) != ESP_OK)
        {
            ESP_LOGW(TAG, "ADC Kalibrierung nicht verfügbar, nutze Fallback");
            s_vbat_cali = NULL;
        }

        s_vbat_configured = true;
    }

    int value = 0;
    for (int i = 0; i < 3; i++)
    {
        adc_oneshot_read(adc, VBAT_ADC_CHANNEL, &value);
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    // Settling-Pause damit S&H-Kondensator und ADC-Referenz vollständig stabil sind
    vTaskDelay(pdMS_TO_TICKS(50));

    const int num_samples = 16;
    int       sum         = 0;
    int       count       = 0;
    for (int i = 0; i < num_samples; i++)
    {
        if (adc_oneshot_read(adc, VBAT_ADC_CHANNEL, &value) == ESP_OK)
        {
            sum += value;
            count++;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (count == 0)
    {
        return 0.0f;
    }
    int raw = sum / count;

    // Raw → kalibrierte Millivolt konvertieren
    int v_adc_mv = 0;
    if (s_vbat_cali)
    {
        adc_cali_raw_to_voltage(s_vbat_cali, raw, &v_adc_mv);
    }
    else
    {
        // Fallback: manuelle Berechnung
        v_adc_mv = (int) ((raw / ADC_MAX_CODE) * 3300.0f);
    }

    float v_bat_mv = v_adc_mv * VBAT_SCALE_FACTOR + VBAT_OFFSET_MV;
    ESP_LOGI(TAG, "Batterie: raw=%d, adc_mv=%d, bat_mv=%.0f", raw, v_adc_mv, v_bat_mv);
    return v_bat_mv / 1000.0f;
#else
    return 0.0f;
#endif
}

static void measure_sensors(void)
{
    // Power Management Lock aktivieren bei Messungen (ADC kritisch)
    if (s_pm_lock)
    {
        esp_pm_lock_acquire(s_pm_lock);
    }

    // ── Phase 1: Temperatur/Luftfeuchte (HTU21D über I2C) ─────────────────
    gpio_power(TEMP_SENSOR_VCC_PIN, true);
    vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));

    if (htu21d_read_temperature(&g_fsm.last_temp) != ESP_OK)
    {
        g_fsm.last_temp = NAN;
    }
    if (htu21d_read_humidity(&g_fsm.last_rh) != ESP_OK)
    {
        g_fsm.last_rh = NAN;
    }
    gpio_power(TEMP_SENSOR_VCC_PIN, false);

    // ── Phase 2: Batterie (alle anderen Sensoren stromlos für minimale ──
    //            Störungen auf der analogen Versorgung)
    vTaskDelay(pdMS_TO_TICKS(50));
    g_fsm.last_vbat = read_battery_voltage();

    // ── Phase 3: Bodenfeuchte ──────────────────────────────────────────────
    gpio_power(SOIL_VCC_PIN, true);
    vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));

    int raw             = read_soil_raw();
    g_fsm.last_soil_raw = raw;
    g_fsm.last_soil_pct = moisture_pct_from_raw(raw);

    gpio_power(SOIL_VCC_PIN, false);

    ESP_LOGI(TAG, "Messung: Boden=%d%% (Raw=%d), Temp=%.1f°C, RH=%.1f%%", g_fsm.last_soil_pct, raw, g_fsm.last_temp, g_fsm.last_rh);

    // Power Management Lock freigeben
    if (s_pm_lock)
    {
        esp_pm_lock_release(s_pm_lock);
    }
}

// ============================================================================
// System-Funktionen
// ============================================================================

static void sys_log_wakeup_reason(void)
{
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();

    switch (cause)
    {
        case ESP_SLEEP_WAKEUP_TIMER:
            ESP_LOGI(TAG, "Aufwachgrund: Timer");
            break;
        case ESP_SLEEP_WAKEUP_GPIO:
            ESP_LOGI(TAG, "Aufwachgrund: GPIO (Button)");
            break;
        case ESP_SLEEP_WAKEUP_EXT0:
            ESP_LOGI(TAG, "Aufwachgrund: EXT0");
            break;
        case ESP_SLEEP_WAKEUP_EXT1:
            ESP_LOGI(TAG, "Aufwachgrund: EXT1");
            break;
        case ESP_SLEEP_WAKEUP_UART:
            ESP_LOGI(TAG, "Aufwachgrund: UART");
            break;
        case ESP_SLEEP_WAKEUP_UNDEFINED:
            ESP_LOGI(TAG, "Aufwachgrund: Power-On/Reset");
            break;
        default:
            ESP_LOGI(TAG, "Aufwachgrund: %d", cause);
            break;
    }
}

static void sys_check_button_wakeup(void)
{
    // Nur echte Resets über die Reset-Taste (EN-Pin) bzw. Power-On zählen.
    // Deep-Sleep-, Software-, Panic-, Watchdog- und Brownout-Resets würden sonst
    // z.B. bei schwachem Akku ungewollt Kalibrierung/Werksreset auslösen.
    esp_reset_reason_t reason = esp_reset_reason();
    if (reason != ESP_RST_POWERON && reason != ESP_RST_EXT)
    {
        return;
    }

    g_state.reset_counter++;

    if (g_state.reset_counter == CALIBRATION_RESET_CLICK_COUNT)
    {
        g_calibration_requested = true;
        ESP_LOGW(TAG, "Kalibrierungsmodus-Sequenz erkannt!");
    }

    if (g_state.reset_counter >= FACTORY_RESET_CLICK_COUNT)
    {
        g_factory_reset_requested = true;
        g_state.reset_counter     = 0;
        ESP_LOGW(TAG, "Factory-Reset Sequenz erkannt!");
    }

    nvs_save_state();
}

static void sys_clear_reset_counter(void)
{
    g_state.reset_counter = 0;
    nvs_save_state();
}

static void sys_perform_factory_reset(void)
{
    ESP_LOGW(TAG, "Factory Reset wird durchgeführt...");

    // NVS löschen
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE_APP, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_erase_all(handle);
        nvs_commit(handle);
        nvs_close(handle);
    }
    if (nvs_open(NVS_NAMESPACE_BUF, NVS_READWRITE, &handle) == ESP_OK)
    {
        nvs_erase_all(handle);
        nvs_commit(handle);
        nvs_close(handle);
    }

    // Defaults setzen
    memset(&g_config, 0, sizeof(g_config));
    g_config.target_soil_pct        = DEFAULT_TARGET_SOIL_PCT;
    g_config.irrigation_start_delta = DEFAULT_IRRIGATION_DELTA;
    g_config.offline_sleep_s        = DEFAULT_OFFLINE_SLEEP_S;

    memset(&g_calib, 0, sizeof(g_calib));
    g_calib.raw_dry = DEFAULT_CALIB_RAW_DRY;
    g_calib.raw_wet = DEFAULT_CALIB_RAW_WET;

    memset(&g_stats, 0, sizeof(g_stats));
    memset(&g_state, 0, sizeof(g_state));

    // RTC-Zeit zurücksetzen
    s_rtc_epoch_base_s = 0;
    s_rtc_time_valid   = 0;
}

static void stats_log(void)
{
    if (g_stats.total_wakeups == 0)
    {
        return;
    }

    ESP_LOGI(TAG, "========== STATISTIK ==========");

    // Wakeup-Statistik
    float avg_awake_s = (float) g_stats.total_awake_ms / 1000.0f / g_stats.total_wakeups;
    ESP_LOGI(TAG, "Wakeups: %lu total, Ø %.2fs wach", (unsigned long) g_stats.total_wakeups, avg_awake_s);

    // Aktueller Zyklus
    ESP_LOGI(TAG,
             "Dieser Zyklus: %lu ms wach, %lu s Sleep geplant",
             (unsigned long) g_stats.last_cycle_awake_ms,
             (unsigned long) g_fsm.sleep_duration_s);

    // Bewässerung in diesem Zyklus
    if (g_fsm.irrigated)
    {
        ESP_LOGI(TAG,
                 "Bewässerung: JA, Pumpe insgesamt %u ms an (Boden=%u%%, Target=%u%%)",
                 (unsigned) g_fsm.irrigation_ms,
                 (unsigned) g_fsm.last_soil_pct,
                 (unsigned) g_config.target_soil_pct);
    }
    else
    {
        ESP_LOGI(TAG, "Bewässerung: nein (Boden=%u%%, Target=%u%%)", (unsigned) g_fsm.last_soil_pct, (unsigned) g_config.target_soil_pct);
    }

    // Gesamte Wachzeit
    uint64_t total_s = g_stats.total_awake_ms / 1000;
    uint64_t hours   = total_s / 3600;
    uint64_t mins    = (total_s % 3600) / 60;
    uint64_t secs    = total_s % 60;
    ESP_LOGI(TAG,
             "Gesamte Wachzeit: %lluh %llum %llus (%llu ms)",
             (unsigned long long) hours,
             (unsigned long long) mins,
             (unsigned long long) secs,
             (unsigned long long) g_stats.total_awake_ms);

    // BLE-Statistik
    if (g_stats.ble_attempts > 0)
    {
        float success_rate = 100.0f * g_stats.ble_success_count / g_stats.ble_attempts;
        ESP_LOGI(TAG,
                 "BLE: %.1f%% Erfolg (%lu/%lu Verbindungen)",
                 success_rate,
                 (unsigned long) g_stats.ble_success_count,
                 (unsigned long) g_stats.ble_attempts);
    }
    else
    {
        ESP_LOGI(TAG, "BLE: Noch keine Verbindungsversuche");
    }

    // Buffer-Status
    ESP_LOGI(TAG, "Buffer: %d/%d Einträge", (int) s_buf_count, MAX_BUFFER_ENTRIES);

    // Zeit-Status
    if (time_is_valid())
    {
        uint32_t unix_now = (uint32_t) time_now_unix_s();
        ESP_LOGI(TAG,
                 "Zeit: Unix=%lu, Syncs=%lu, Drift=%ld s",
                 (unsigned long) unix_now,
                 (unsigned long) s_rtc_sync_count,
                 (long) s_rtc_last_drift_s);
    }
    else
    {
        ESP_LOGI(TAG, "Zeit: Nicht synchronisiert");
    }

    // System-Info
    ESP_LOGI(TAG,
             "System: Heap=%lu Bytes frei, Messung #%lu",
             (unsigned long) esp_get_free_heap_size(),
             (unsigned long) g_state.measurement_id);

    // Energieeffizienz-Schätzung (falls genug Daten)
    if (g_stats.total_wakeups >= 5 && g_stats.last_sleep_duration_s > 0)
    {
        float duty_cycle = avg_awake_s / (avg_awake_s + g_stats.last_sleep_duration_s) * 100.0f;
        float sleep_pct  = 100.0f - duty_cycle;
        ESP_LOGI(TAG, "Energieeffizienz: %.2f%% Sleep, %.2f%% Wach", sleep_pct, duty_cycle);
    }

    ESP_LOGI(TAG, "================================");
}

// ============================================================================
// Cycle-Stats Log
// ============================================================================

// Einzeiliges Log der State-Dauern des aktuellen Wake-Cycles
static void cycle_stats_log(uint32_t total_awake_ms)
{
    ESP_LOGI(TAG,
             "[CYCLE-STATS] wakeup=%lu init=%lu first_setup=%lu measure=%lu "
             "ble=%lu irrigation=%lu calibration=%lu display=%lu shutdown=%lu "
             "total_awake=%lu pump_on=%lu irrigated=%d",
             (unsigned long) g_stats.total_wakeups,
             (unsigned long) s_cycle_state_ms[STATE_INIT],
             (unsigned long) s_cycle_state_ms[STATE_FIRST_SETUP],
             (unsigned long) s_cycle_state_ms[STATE_MEASURE],
             (unsigned long) s_cycle_state_ms[STATE_BLE_SEND_RECEIVE],
             (unsigned long) s_cycle_state_ms[STATE_IRRIGATION],
             (unsigned long) s_cycle_state_ms[STATE_CALIBRATION],
             (unsigned long) s_cycle_state_ms[STATE_UPDATE_DISPLAY],
             (unsigned long) s_cycle_state_ms[STATE_SLEEP],
             (unsigned long) total_awake_ms,
             (unsigned long) g_fsm.irrigation_ms,
             g_fsm.irrigated ? 1 : 0);
}

// ============================================================================
// FSM: State-Übergang
// ============================================================================

static const char* state_name(system_state_t state)
{
    static const char* names[] = { "INIT",        "FIRST_SETUP", "MEASURE",       "BLE",   "IRRIGATION",
                                   "CALIBRATION", "DISPLAY",     "FACTORY_RESET", "SLEEP", "ERROR" };

    if (state < sizeof(names) / sizeof(names[0]))
    {
        return names[state];
    }
    return "UNKNOWN";
}

static void state_enter(system_state_t new_state)
{
    uint64_t now_us = esp_timer_get_time();

    // Vorherigen State loggen (außer beim ersten Aufruf)
    if (s_state_enter_us > 0 && g_fsm.state != new_state)
    {
        uint32_t duration_ms = (now_us - s_state_enter_us) / 1000;
        if ((int) g_fsm.state >= 0 && (int) g_fsm.state < FSM_STATE_COUNT)
        {
            s_cycle_state_ms[g_fsm.state] += duration_ms;
        }
        ESP_LOGI(TAG, "State %s: %lu ms", state_name(g_fsm.state), (unsigned long) duration_ms);
    }

    // Neuen State setzen
    g_fsm.state      = new_state;
    s_state_enter_us = now_us;

    // State-Wechsel loggen
    ESP_LOGI(TAG, ">>> State: %s", state_name(new_state));
}

// ============================================================================
// FSM: STATE_INIT
// ============================================================================

static void state_init_handler(void)
{
    g_boot_time_us = rtc_now_us();
    ESP_LOGI(TAG, "Initialisierung...");

    // Power Management initialisieren
    sys_init_power_management();

    // NVS initialisieren
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND)
    {
        ESP_LOGW(TAG, "NVS wird gelöscht und neu initialisiert");
        nvs_flash_erase();
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "NVS Initialisierung fehlgeschlagen");
        state_enter(STATE_ERROR);
        return;
    }

    // Persistente Daten laden
    load_all_persistent_data();

    // Buffer-Metadaten laden
    buf_load_meta();

    // Wakeup-Grund loggen und Factory-Reset prüfen
    sys_log_wakeup_reason();
    sys_check_button_wakeup();

    // I2C initialisieren
    i2c_utils_cfg_t i2c_cfg = { .port             = I2C_PORT,
                                .sda_gpio         = I2C_SDA_GPIO,
                                .scl_gpio         = I2C_SCL_GPIO,
                                .clk_hz           = I2C_CLK_HZ,
                                .timeout_ms       = I2C_TIMEOUT_MS,
                                .internal_pullups = I2C_PULLUPS };
    if (i2c_utils_init(&i2c_cfg) != ESP_OK)
    {
        ESP_LOGE(TAG, "I2C Initialisierung fehlgeschlagen");
        state_enter(STATE_ERROR);
        return;
    }

    // Display initialisieren
    gpio_power(DISPLAY_VCC_PIN, true);
    vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));

    display_hal_config_t display_cfg = { .spi_host    = SPI2_HOST,
                                         .pin_mosi    = PIN_MOSI,
                                         .pin_sclk    = PIN_SCLK,
                                         .pin_cs      = PIN_CS,
                                         .pin_dc      = PIN_DC,
                                         .pin_rst     = PIN_RST,
                                         .pin_busy    = PIN_BUSY,
                                         .spi_hz      = SPI_HZ,
                                         .upside_down = DISPLAY_UPSIDE_DOWN,
                                         .debug       = DISPLAY_DEBUG };

    s_display_ok = (display_ui_init(&display_cfg) == ESP_OK);
    if (!s_display_ok)
    {
        // Messen und Bewässern funktionieren auch ohne Anzeige weiter
        ESP_LOGE(TAG, "Display nicht verfügbar, Betrieb ohne Anzeige");
        gpio_power(DISPLAY_VCC_PIN, false);
    }

    // Sensoren initialisieren
    soil_cfg_t soil_cfg = { .adc_unit = SOIL_ADC_UNIT, .adc_channel = SOIL_ADC_CHANNEL, .do_gpio = SOIL_DO_GPIO, .samples = SOIL_SAMPLES };
    if (soil_init(&soil_cfg) != ESP_OK)
    {
        ESP_LOGW(TAG, "Bodensensor-Init fehlgeschlagen");
    }

    gpio_power(TEMP_SENSOR_VCC_PIN, true);
    vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));
    if (htu21d_init() != ESP_OK)
    {
        ESP_LOGW(TAG, "HTU21D-Init fehlgeschlagen");
    }
    gpio_power(TEMP_SENSOR_VCC_PIN, false);

    // Button konfigurieren
    gpio_config_t btn_cfg = { .pin_bit_mask = 1ULL << BTN_GPIO,
                              .mode         = GPIO_MODE_INPUT,
                              .pull_up_en   = GPIO_PULLUP_ENABLE,
                              .pull_down_en = GPIO_PULLDOWN_DISABLE,
                              .intr_type    = GPIO_INTR_DISABLE };
    gpio_config(&btn_cfg);

    // BLE initialisieren
    if (ble_link_init(BLE_DEVICE_NAME) != ESP_OK)
    {
        ESP_LOGE(TAG, "BLE Init fehlgeschlagen");
    }

    // Factory-Reset Modus?
    if (g_factory_reset_requested)
    {
        display_ui_show_factory_reset_confirm();
        state_enter(STATE_FACTORY_RESET);
        return;
    }

    // Kalibrierungsmodus via Reset-Sequenz?
    if (g_calibration_requested)
    {
        g_calibration_requested = false;
        gpio_power(DISPLAY_VCC_PIN, false);
        state_enter(STATE_CALIBRATION);
        return;
    }

    // Erst-Einrichtung oder normaler Betrieb?
    if (!g_state.initial_setup_done)
    {
        // Nach einem Setup-Timeout zeigt das E-Paper den Setup-Bildschirm noch an,
        // ein erneutes Zeichnen würde nur Strom kosten
        if (!(s_rtc_setup_retry && esp_reset_reason() == ESP_RST_DEEPSLEEP))
        {
            display_ui_show_setup_screen();
        }
        s_rtc_setup_retry = 0;
        gpio_power(DISPLAY_VCC_PIN, false);
        memset(&g_stats, 0, sizeof(g_stats));
        state_enter(STATE_FIRST_SETUP);
    }
    else
    {
        gpio_power(DISPLAY_VCC_PIN, false);
        state_enter(STATE_MEASURE);
    }
}

// ============================================================================
// FSM: STATE_FIRST_SETUP
// ============================================================================

// Setup-Timeout: Teilweise empfangene Einstellungen sichern, schlafen und später erneut versuchen
static void setup_retry_later(bool config_changed)
{
    if (config_changed)
    {
        nvs_save_config();
    }
    s_rtc_setup_retry      = 1;
    g_fsm.sleep_duration_s = SETUP_RETRY_SLEEP_S;
    state_enter(STATE_SLEEP);
}

static void state_first_setup_handler(void)
{
    bool               got_time       = false;
    bool               got_sleep      = false;
    bool               got_target     = false;
    bool               config_changed = false;
    ble_link_control_t ctrl           = { 0 };
    uint32_t           start_tick     = xTaskGetTickCount();

    for (;;)
    {
        // ── Phase 1: Auf BLE-Verbindung warten (höchstens SETUP_WAIT_TIMEOUT_MS) ──
        got_time   = false;
        got_sleep  = false;
        got_target = false;

        ESP_LOGI(TAG, "Setup: Warte auf BLE-Verbindung...");
        while (!ble_link_client_ready())
        {
            if ((xTaskGetTickCount() - start_tick) * portTICK_PERIOD_MS > SETUP_WAIT_TIMEOUT_MS)
            {
                ESP_LOGW(TAG, "Setup: Kein Host gefunden, neuer Versuch in %d s", SETUP_RETRY_SLEEP_S);
                setup_retry_later(config_changed);
                return;
            }
            vTaskDelay(pdMS_TO_TICKS(BLE_POLL_MS));
        }
        g_fsm.ble_connected = true;
        ESP_LOGI(TAG, "Setup: BLE verbunden");

        // ── Phase 2: Steuerbefehle empfangen bis alle 3 Werte da ───────────
        while (!got_time || !got_sleep || !got_target)
        {
            // Auch mit Verbindung nicht endlos wach bleiben, wenn das verbundene Gerät
            // nie alle Werte schickt (sonst wäre der Akku irgendwann leer)
            if ((xTaskGetTickCount() - start_tick) * portTICK_PERIOD_MS > SETUP_WAIT_TIMEOUT_MS)
            {
                ESP_LOGW(TAG, "Setup: Konfiguration unvollständig, neuer Versuch in %d s", SETUP_RETRY_SLEEP_S);
                setup_retry_later(config_changed);
                return;
            }

            memset(&ctrl, 0, sizeof(ctrl));
            ble_link_wait_for_control(BLE_COMMAND_TIMEOUT_MS, &ctrl);

            if (!ble_link_is_connected())
            {
                ESP_LOGW(TAG, "Setup: Verbindung verloren, warte erneut...");
                g_fsm.ble_connected = false;
                break;
            }

            // Eingaben validieren
            validate_control(&ctrl);

            if (ctrl.have_unix_time)
            {
                time_sync_from_host(ctrl.unix_time);
                got_time = true;
            }

            if (ctrl.have_offline_sleep)
            {
                if (g_config.offline_sleep_s != ctrl.offline_sleep_s)
                {
                    g_config.offline_sleep_s = ctrl.offline_sleep_s;
                    config_changed           = true;
                    ESP_LOGI(TAG, "Setup: Offline-Sleep auf %u s gesetzt", ctrl.offline_sleep_s);
                }
                got_sleep = true;
            }

            if (ctrl.have_target_soil)
            {
                if (g_config.target_soil_pct != ctrl.target_soil_pct)
                {
                    g_config.target_soil_pct = ctrl.target_soil_pct;
                    config_changed           = true;
                    ESP_LOGI(TAG, "Setup: Ziel-Bodenfeuchte auf %u%% gesetzt", ctrl.target_soil_pct);
                }
                got_target = true;
            }

            // Delta ist für das Setup nicht Pflicht, wird aber übernommen, damit
            // auch der erste Offline-Zyklus mit dem eingestellten Wert rechnet
            if (ctrl.have_irrigation_start_delta && g_config.irrigation_start_delta != ctrl.irrigation_start_delta)
            {
                g_config.irrigation_start_delta = ctrl.irrigation_start_delta;
                config_changed                  = true;
                ESP_LOGI(TAG, "Setup: Bewässerungs-Delta auf %u%% gesetzt", ctrl.irrigation_start_delta);
            }
        }

        // Alle 3 Werte da → raus aus der Retry-Schleife
        if (got_time && got_sleep && got_target)
        {
            break;
        }
    }

    // ── Phase 3: Setup abschließen ─────────────────────────────────────────
    if (config_changed)
    {
        nvs_save_config();
    }

    if (!g_state.initial_setup_done)
    {
        g_state.initial_setup_done = true;
        nvs_save_state();
        memset(&g_stats, 0, sizeof(g_stats));
        g_boot_time_us = rtc_now_us();

        g_fsm.sleep_duration_s = 5;
        ESP_LOGI(TAG, "First-Setup abgeschlossen, kurzer Deep Sleep vor erstem Mess-Zyklus");
        state_enter(STATE_SLEEP);
        return;
    }

    state_enter(STATE_MEASURE);
}

// ============================================================================
// FSM: STATE_MEASURE
// ============================================================================

static void state_measure_handler(void)
{
    measure_sensors();

    // Messungs-ID erhöhen
    g_state.measurement_id++;
    nvs_save_state();

    // Statistiken berechnen
    float avg_awake = 0.0f;
    if (g_stats.total_wakeups > 0)
    {
        avg_awake = (float) g_stats.total_awake_ms / 1000.0f / g_stats.total_wakeups;
    }

    float ble_success = 0.0f;
    if (g_stats.ble_attempts > 0)
    {
        ble_success = 100.0f * g_stats.ble_success_count / g_stats.ble_attempts;
    }

    g_current_meas.measurement_id = g_state.measurement_id;
    g_current_meas.temp_c         = g_fsm.last_temp;
    g_current_meas.rh_pct         = g_fsm.last_rh;
    g_current_meas.soil_pct       = g_fsm.last_soil_pct;
    g_current_meas.soil_raw       = g_fsm.last_soil_raw;
    g_current_meas.unix_time      = (uint32_t) time_now_unix_s();

    g_current_meas.irrigated     = g_fsm.irrigated ? 1 : 0;
    g_current_meas.irrigation_ms = g_fsm.irrigation_ms;
    g_current_meas.pump_dry      = g_fsm.pump_dry ? 1 : 0;

    g_current_meas.battery_voltage        = g_fsm.last_vbat;
    g_current_meas.target_soil_pct        = g_config.target_soil_pct;
    g_current_meas.irrigation_start_delta = g_config.irrigation_start_delta;
    g_current_meas.offline_sleep_s        = g_config.offline_sleep_s;
    g_current_meas.calib_raw_dry          = g_calib.raw_dry;
    g_current_meas.calib_raw_wet          = g_calib.raw_wet;

    g_current_meas.total_wakeups         = g_stats.total_wakeups;
    g_current_meas.avg_awake_s           = avg_awake;
    g_current_meas.ble_success_pct       = ble_success;
    g_current_meas.total_irrigation_ms   = g_stats.total_irrigation_ms;
    g_current_meas.total_awake_ms        = g_stats.total_awake_ms;
    g_current_meas.last_awake_time_ms    = g_stats.last_cycle_awake_ms;
    g_current_meas.last_sleep_duration_s = g_stats.last_sleep_duration_s;
    g_current_meas.uptime_seconds        = (uint32_t) rtc_now_s();
    g_current_meas.free_heap_bytes       = esp_get_free_heap_size();
    g_current_meas.reset_reason          = (uint8_t) esp_reset_reason();

    // Online-Flag beim Erzeugen erstmal 0, wird beim Senden gesetzt
    g_current_meas.online = 0;
    g_current_meas_valid  = true;

    if (g_fsm.irrigated)
    { // in diesem Zyklus wurde schon gegossen daher speichern und dann Display aktualisieren
        store_measurement_if_needed();
        state_enter(STATE_UPDATE_DISPLAY);
        return;
    }

    state_enter(STATE_BLE_SEND_RECEIVE);
}

// Verdunstungs-Index (0-8) basierend auf Temperatur × Luftfeuchtigkeit.
// Gleiche Tabelle wie Host-Brain (brain.py EVAP_TABLE).
// Hoher Wert = schnelle Verdunstung = Boden trocknet schneller aus.
//
//              >70%RH   40-70%RH   <40%RH
//   <15°C  :    0         1          2
//   15-29°C:    1         3          5
//   ≥30°C  :    2         5          8
static const uint8_t EVAP_TABLE[3][3] = {
    { 0, 1, 2 },
    { 1, 3, 5 },
    { 2, 5, 8 },
};

// Verdunstungs-Index aus EVAP_TABLE (0 wenn Temperatur oder Luftfeuchte fehlen)
static int evap_index(float temp_c, float rh_pct)
{
    if (isnan(temp_c) || isnan(rh_pct))
    {
        return 0;
    }
    int ti = (temp_c < 15.0f) ? 0 : (temp_c < 30.0f) ? 1 : 2;
    int hi = (rh_pct > 70.0f) ? 0 : (rh_pct >= 40.0f) ? 1 : 2;
    return EVAP_TABLE[ti][hi];
}

// Berechnet adaptive Offline-Sleep-Dauer.
// Simpler Fallback wenn Host nicht erreichbar — bewusst einfacher als
// die Host-Brain (kein History, kein Wetter, keine Trends).
//
// Zwei Faktoren:
//   1) Soil-Margin:  nah am Threshold → kürzer, weit weg → länger
//   2) Evaporation:  heiß+trocken → kürzer (linear, evap 0→1.0, evap 8→0.5)
static uint32_t calc_offline_sleep_s(uint32_t base_s, int soil_pct, int threshold, float temp_c, float rh_pct)
{
    int      margin  = soil_pct - threshold;
    uint32_t sleep_s = base_s;

    // Soil-Margin: wie weit ist der Boden vom Gieß-Schwellwert entfernt?
    if (margin <= 5)
    {
        sleep_s = base_s / 2; // fast trocken → öfter prüfen
    }
    else if (margin > 20)
    {
        sleep_s = base_s * 3 / 2; // sehr feucht → seltener prüfen
    }

    // Evaporation: linearer Faktor von 1.0 (evap=0) bis 0.5 (evap=8)
    int evap = evap_index(temp_c, rh_pct);
    sleep_s  = sleep_s * (16 - evap) / 16;

    // Minimum: base/4 (skaliert mit User-Konfiguration, kein harter Wert)
    uint32_t min_s = base_s / 4;
    if (sleep_s < min_s)
        sleep_s = min_s;

    return sleep_s;
}

// ============================================================================
// FSM: STATE_BLE_SEND_RECEIVE
// ============================================================================

static void state_ble_send_receive_handler(void)
{
    g_stats.ble_attempts++;
    g_fsm.sleep_duration_s = g_config.offline_sleep_s;

    // ── Phase 1: Auf Verbindung warten ──────────────────────────────────────
    ESP_LOGI(TAG, "BLE: Warte auf Verbindung (max %d ms)", BLE_CONNECT_TIMEOUT_MS);
    bool     connected  = false;
    uint32_t start_tick = xTaskGetTickCount();
    while (((xTaskGetTickCount() - start_tick) * portTICK_PERIOD_MS) < BLE_CONNECT_TIMEOUT_MS)
    {
        if (ble_link_client_ready())
        {
            connected = true;
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(BLE_POLL_MS));
    }
    g_fsm.ble_connected = connected;

    if (!connected)
    {
        ESP_LOGW(TAG, "BLE: Keine Verbindung innerhalb %d ms", BLE_CONNECT_TIMEOUT_MS);
    }

    // ── Phase 2: Daten senden ───────────────────────────────────────────────
    if (connected)
    {
        ESP_LOGI(TAG, "BLE: Verbunden, sende Daten...");
        buf_flush_and_send();

        if (g_current_meas_valid)
        {
            g_current_meas.online = 1;
            if (ble_link_send_measurement(&g_current_meas) == ESP_OK)
            {
                ESP_LOGI(TAG, "Aktuelle Messung gesendet (ID=%lu)", (unsigned long) g_current_meas.measurement_id);
                g_current_meas_valid = false;
                g_stats.ble_success_count++;
            }
            else
            {
                ESP_LOGW(TAG, "Senden der aktuellen Messung fehlgeschlagen");
            }
        }
    }

    // ── Phase 3: Auf Steuerbefehle warten ───────────────────────────────────
    ble_link_control_t ctrl        = { 0 };
    bool               got_control = false;
    if (connected)
    {
        ESP_LOGI(TAG, "BLE: Warte auf Steuerbefehle (max %d ms)", BLE_COMMAND_TIMEOUT_MS);
        got_control = ble_link_wait_for_control(BLE_COMMAND_TIMEOUT_MS, &ctrl);
    }

    // ── Phase 4: Befehle verarbeiten + nächsten State bestimmen ─────────────
    if (got_control)
    {
        // Eingaben validieren
        validate_control(&ctrl);

        if (ctrl.have_unix_time)
        {
            time_sync_from_host(ctrl.unix_time);
        }

        bool config_changed = false;

        if (ctrl.have_target_soil)
        {
            if (g_config.target_soil_pct != ctrl.target_soil_pct)
            {
                g_config.target_soil_pct = ctrl.target_soil_pct;
                config_changed           = true;
                ESP_LOGI(TAG, "Target Soil auf %u%% gesetzt", ctrl.target_soil_pct);
            }
        }

        if (ctrl.have_irrigation_start_delta)
        {
            if (g_config.irrigation_start_delta != ctrl.irrigation_start_delta)
            {
                g_config.irrigation_start_delta = ctrl.irrigation_start_delta;
                config_changed                  = true;
                ESP_LOGI(TAG, "Irrigation Start Delta auf %u%% gesetzt", ctrl.irrigation_start_delta);
            }
        }

        if (ctrl.have_offline_sleep)
        {
            if (g_config.offline_sleep_s != ctrl.offline_sleep_s)
            {
                g_config.offline_sleep_s = ctrl.offline_sleep_s;
                config_changed           = true;
                ESP_LOGI(TAG, "Offline Sleep auf %lu s gesetzt", (unsigned long) ctrl.offline_sleep_s);
            }
        }

        if (config_changed)
        {
            nvs_save_config();
            ESP_LOGI(TAG, "Neue Konfiguration im NVS gespeichert");
        }

        if (ctrl.have_sleep_s)
        {
            g_fsm.sleep_duration_s = ctrl.sleep_seconds;
            ESP_LOGI(TAG, "Sleep-Zeit vom Host: %lus", (unsigned long) g_fsm.sleep_duration_s);
        }
    }

    // Messung puffern falls nicht gesendet
    store_measurement_if_needed();

    // State-Übergang bestimmen
    if (got_control && ctrl.have_irrigation_request && !g_fsm.irrigated)
    {
        ESP_LOGI(TAG, "Gieß-Anforderung vom Host empfangen");
        g_fsm.should_irrigate = true;
        ble_link_stop();
        state_enter(STATE_IRRIGATION);
        return;
    }

    // Nach einer Brain-Entscheidung schickt der Host immer eine Schlafzeit. Kam keine
    // (z.B. weil die Messung nicht ankam und nur Config und Zeit übertragen wurden),
    // entscheidet der Knoten wie im Offline-Fall selbst.
    bool host_decided = got_control && ctrl.have_sleep_s;

    if (!host_decided)
    {
        // Schwelle = max(target - delta, target * 20%, 5%)
        // Skaliert mit dem Target, damit z.B. Sukkulenten (Target 25%) ein
        // niedrigeres Minimum bekommen als Standardpflanzen (Target 50%).
        int threshold  = (int) g_config.target_soil_pct - (int) g_config.irrigation_start_delta;
        int target_min = (int) g_config.target_soil_pct * IRR_THRESHOLD_TARGET_FACTOR / 100;
        if (target_min < IRR_THRESHOLD_MIN_PCT)
        {
            target_min = IRR_THRESHOLD_MIN_PCT;
        }
        if (threshold < target_min)
        {
            threshold = target_min;
        }

        // Gieß-Schwelle wie im Host-Brain um den Verdunstungs-Index anheben:
        // irr_threshold = max(target - delta + evap, target_min), höchstens target - Toleranz
        int irr_threshold =
            (int) g_config.target_soil_pct - (int) g_config.irrigation_start_delta + evap_index(g_fsm.last_temp, g_fsm.last_rh);
        if (irr_threshold < target_min)
        {
            irr_threshold = target_min;
        }
        // Darüber würde der Gießvorgang sofort wieder enden (Toleranz zum Ziel)
        if (irr_threshold > (int) g_config.target_soil_pct - IRR_TARGET_TOLERANCE_PCT)
        {
            irr_threshold = (int) g_config.target_soil_pct - IRR_TARGET_TOLERANCE_PCT;
        }

        g_fsm.sleep_duration_s =
            calc_offline_sleep_s(g_config.offline_sleep_s, g_fsm.last_soil_pct, threshold, g_fsm.last_temp, g_fsm.last_rh);

        ESP_LOGW(TAG,
                 "Offline: Boden=%d%%, Schwelle=%d%% (Gießen unter %d%%), Target=%d%%, Sleep=%lus",
                 g_fsm.last_soil_pct,
                 threshold,
                 irr_threshold,
                 g_config.target_soil_pct,
                 (unsigned long) g_fsm.sleep_duration_s);

        if (g_fsm.irrigated)
        {
            ESP_LOGI(TAG, "Offline: bereits gegossen, überspringe");
        }
        else if (!isnan(g_fsm.last_temp) && g_fsm.last_temp <= 0.0f)
        {
            ESP_LOGW(TAG, "Offline: Frost-Sperre (%.1f°C <= 0°C), keine Bewässerung", g_fsm.last_temp);
        }
        else if (g_fsm.last_soil_pct >= irr_threshold)
        {
            ESP_LOGI(TAG, "Offline: Boden feucht genug, kein Gießen");
        }
        else
        {
            ESP_LOGW(TAG, "Offline: Boden zu trocken, starte Bewässerung");
            g_fsm.should_irrigate = true;
            ble_link_stop();
            state_enter(STATE_IRRIGATION);
            return;
        }
    }

    ble_link_stop();
    state_enter(STATE_UPDATE_DISPLAY);
}

// ============================================================================
// FSM: STATE_IRRIGATION
// ============================================================================

static void state_irrigation_handler(void)
{
    // Sicherheitsnetz: nur gießen, wenn es explizit angefordert wurde
    if (!g_fsm.should_irrigate || g_fsm.irrigated)
    {
        ESP_LOGW(TAG, "IRR: nichts zu tun (should_irrigate=%d, irrigated=%d)", g_fsm.should_irrigate, g_fsm.irrigated);
        state_enter(STATE_UPDATE_DISPLAY);
        return;
    }

    ESP_LOGI(TAG, "IRR: Starte Bewässerung");

    uint32_t total_ms   = 0;
    int      steps      = 0;     // bisherige Gießschritte
    int      start_soil = -1;    // Bodenfeuchte vor dem ersten Gießschritt
    bool     rise_seen  = false; // Bodenfeuchte ist durch das Gießen gestiegen
    bool     pump_dry   = false;

    while (total_ms < IRR_MAX_TOTAL_MS)
    {
        // 1) aktuelle Bodenfeuchte messen
        if (s_pm_lock)
            esp_pm_lock_acquire(s_pm_lock);

        gpio_power(SOIL_VCC_PIN, true);
        vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));

        uint16_t soil_raw = read_soil_raw();

        gpio_power(SOIL_VCC_PIN, false);
        if (s_pm_lock)
            esp_pm_lock_release(s_pm_lock);

        uint8_t soil   = moisture_pct_from_raw(soil_raw);
        uint8_t target = g_config.target_soil_pct;

        // Abstand berechnen
        int diff = (int) target - (int) soil;

        ESP_LOGI(TAG, "IRR: Boden=%u%%, Target=%u%% (diff=%d)", soil, target, diff);

        if (start_soil < 0)
        {
            start_soil = soil;
        }
        else if (soil >= start_soil + IRR_DRY_MIN_RISE_PCT)
        {
            rise_seen = true;
        }

        // Abbruchbedingung 1: Ziel erreicht oder überschritten
        if (diff <= 0)
        {
            ESP_LOGI(TAG, "IRR: Ziel erreicht!");
            break;
        }

        // Abbruchbedingung 2: Toleranz-Bereich (Acceptable Delta)
        // Wenn wir z.B. nur noch 2% weg sind, stoppen wir, um Überschwingen zu vermeiden.
        if (diff <= IRR_TARGET_TOLERANCE_PCT)
        {
            ESP_LOGI(TAG, "IRR: Toleranzbereich erreicht (%d%% <= %d%%), stoppe.", diff, IRR_TARGET_TOLERANCE_PCT);
            break;
        }

        // Abbruchbedingung 3: Trockenlauf. Die Pumpe lief schon mehrmals, der Boden
        // wird aber nicht feuchter. Weiterpumpen würde die Pumpe nur beschädigen.
        if (!rise_seen && steps >= IRR_DRY_CHECK_STEPS)
        {
            ESP_LOGW(TAG, "IRR: Nach %d Schritten kein Anstieg (%d%% -> %u%%), Tank leer? Abbruch.", steps, start_soil, soil);
            pump_dry = true;
            break;
        }

        // 2) Adaptive Schrittweite berechnen
        uint32_t step_ms;

        if (diff >= 15)
        {
            step_ms = IRR_STEP_LARGE_MS; // 4s
            ESP_LOGI(TAG, ">> Diff groß (%d%%) -> %dms Gießen", diff, (int) step_ms);
        }
        else if (diff >= 5)
        {
            step_ms = IRR_STEP_MED_MS; // 2s
            ESP_LOGI(TAG, ">> Diff mittel (%d%%) -> %dms Gießen", diff, (int) step_ms);
        }
        else
        {
            step_ms = IRR_STEP_SMALL_MS; // 1s
            ESP_LOGI(TAG, ">> Diff klein (%d%%) -> %dms Gießen", diff, (int) step_ms);
        }

        // Sicherheitscheck: Nicht das Hard-Limit überschreiten
        if (total_ms + step_ms > IRR_MAX_TOTAL_MS)
        {
            step_ms = IRR_MAX_TOTAL_MS - total_ms;
        }

        if (step_ms == 0)
            break;

        // 3) Pumpe einschalten und nach step_ms wieder ausschalten
        pump_set(true);
        vTaskDelay(pdMS_TO_TICKS(step_ms));
        pump_set(false);

        total_ms += step_ms;
        steps++;

        // 4) Einsickern lassen
        ESP_LOGI(TAG, "Sicker lassen...");
        vTaskDelay(pdMS_TO_TICKS(IRR_SOAK_MS));
    }

    g_fsm.irrigated       = (total_ms > 0);
    g_fsm.irrigation_ms   = total_ms;
    g_fsm.pump_dry        = pump_dry;
    g_fsm.should_irrigate = false; // für diesen Zyklus erledigt

    g_stats.total_irrigation_ms += total_ms;

    ESP_LOGI(TAG, "IRR: Fertig. Pumpenlaufzeit gesamt: %u ms", (unsigned) total_ms);

    // Nur nach echtem Gießen neu messen. Ohne Wirkung (Ziel schon erreicht) direkt
    // zur Anzeige: Sonst ginge es über MEASURE zurück in den BLE-State, ohne
    // Advertising wieder in die Offline-Entscheidung und erneut zum Gießen.
    state_enter(g_fsm.irrigated ? STATE_MEASURE : STATE_UPDATE_DISPLAY);
}

// ============================================================================
// FSM: STATE_CALIBRATION
// ============================================================================

// Wartet auf einen vollständigen Tastendruck (Drücken + Loslassen) der Boot-Taste.
// Gibt false zurück, wenn vorher das Kalibrierungs-Timeout abläuft.
static bool calibration_wait_for_button(uint32_t start_tick)
{
    // Eine vom vorherigen Schritt noch gedrückte Taste zählt nicht als neuer Druck
    bool released = gpio_get_level(BTN_GPIO);

    for (;;)
    {
        if ((xTaskGetTickCount() - start_tick) * portTICK_PERIOD_MS > CALIBRATION_TIMEOUT_MS)
        {
            return false;
        }

        if (gpio_get_level(BTN_GPIO))
        {
            released = true;
        }
        else if (released)
        {
            vTaskDelay(pdMS_TO_TICKS(50)); // Entprellung
            if (!gpio_get_level(BTN_GPIO))
            {
                return true;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// Beendet den Kalibrierungsmodus, auch nach einem Timeout
static void calibration_exit(void)
{
    gpio_power(SOIL_VCC_PIN, false);
    gpio_power(DISPLAY_VCC_PIN, false);

    // Reset-Zähler zurücksetzen, damit ein weiterer Reset nicht als Teil der
    // Werksreset-Sequenz zählt
    sys_clear_reset_counter();

    // Neustart damit STATE_INIT den First-Setup-Check korrekt durchläuft
    esp_restart();
}

static void state_calibration_handler(void)
{
    ESP_LOGI(TAG, "Kalibrierungsmodus gestartet");

    uint32_t start_tick = xTaskGetTickCount();

    gpio_power(DISPLAY_VCC_PIN, true);
    gpio_power(SOIL_VCC_PIN, true);
    vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));

    // Schritt 1: Trockener Sensor
    display_ui_show_calibration_step1();

    if (!calibration_wait_for_button(start_tick))
    {
        display_ui_show_calibration_timeout();
        calibration_exit();
        return;
    }

    int raw_dry = read_soil_raw();

    // Schritt 2: Nasser Sensor
    display_ui_show_calibration_step2();

    if (!calibration_wait_for_button(start_tick))
    {
        display_ui_show_calibration_timeout();
        calibration_exit();
        return;
    }

    int raw_wet = read_soil_raw();

    gpio_power(SOIL_VCC_PIN, false);

    // Plausibilitätsprüfung: Trocken muss deutlich über Nass liegen. Sonst wären
    // z.B. bei vertauschten Schritten alle Messungen 0% und es würde dauerhaft gegossen.
    if (raw_dry - raw_wet < CALIB_MIN_SPAN_RAW)
    {
        ESP_LOGW(TAG, "Kalibrierung ungültig (dry=%d, wet=%d), alte Werte bleiben", raw_dry, raw_wet);
        display_ui_show_calibration_failed(raw_dry, raw_wet);
    }
    else
    {
        // Kalibrierung speichern und anzeigen
        g_calib.raw_dry = (uint16_t) raw_dry;
        g_calib.raw_wet = (uint16_t) raw_wet;
        nvs_save_calib();
        display_ui_show_calibration_success(g_calib.raw_dry, g_calib.raw_wet);
    }

    // Warten bis Boot-Taste gedrückt wird (spätestens nach dem Timeout weiter)
    calibration_wait_for_button(xTaskGetTickCount());

    calibration_exit();
}

// ============================================================================
// FSM: STATE_UPDATE_DISPLAY
// ============================================================================

static void state_update_display_handler(void)
{
    uint32_t now  = (uint32_t) time_now_unix_s();
    uint32_t next = now + g_fsm.sleep_duration_s;

    // Statistiken berechnen
    float avg_awake = 0.0f;
    if (g_stats.total_wakeups > 0)
    {
        avg_awake = (float) g_stats.total_awake_ms / 1000.0f / g_stats.total_wakeups;
    }

    float ble_success = 0.0f;
    if (g_stats.ble_attempts > 0)
    {
        ble_success = 100.0f * g_stats.ble_success_count / g_stats.ble_attempts;
    }

    // Display-Daten zusammenstellen
    display_ui_data_t data = { .temp_c                = g_fsm.last_temp,
                               .rh_pct                = g_fsm.last_rh,
                               .soil_pct              = g_fsm.last_soil_pct,
                               .target_soil_pct       = g_config.target_soil_pct,
                               .last_measurement_unix = now,
                               .next_measurement_unix = next,
                               .time_valid            = time_is_valid(),
                               .buffer_count          = s_buf_count,
                               .battery_voltage       = g_fsm.last_vbat,
                               .ble_connected         = g_fsm.ble_connected,
                               .soil_raw              = g_fsm.last_soil_raw,
                               .calib_raw_dry         = g_calib.raw_dry,
                               .calib_raw_wet         = g_calib.raw_wet,
                               .measurement_id        = g_state.measurement_id,
                               .sleep_duration_s      = g_fsm.sleep_duration_s,
                               .total_wakeups         = g_stats.total_wakeups,
                               .avg_awake_s           = avg_awake,
                               .ble_success_pct       = ble_success,
                               .last_irrigation_ms    = g_fsm.irrigation_ms };

    // Ohne funktionierendes Display gar nicht erst einschalten (spart Strom und Wachzeit)
    if (s_display_ok)
    {
        gpio_power(DISPLAY_VCC_PIN, true);
        vTaskDelay(pdMS_TO_TICKS(VCC_INIT_TIME));
        display_ui_show_normal_screen(&data);
        gpio_power(DISPLAY_VCC_PIN, false);
    }

    state_enter(STATE_SLEEP);
}

// ============================================================================
// FSM: STATE_FACTORY_RESET
// ============================================================================

static void state_factory_reset_handler(void)
{
    uint32_t start_tick = xTaskGetTickCount();

    while (true)
    {
        // Timeout: Abbrechen und sauber neu starten
        if ((xTaskGetTickCount() - start_tick) * portTICK_PERIOD_MS > FACTORY_RESET_CONFIRM_TIMEOUT_MS)
        {
            sys_clear_reset_counter();
            gpio_power(DISPLAY_VCC_PIN, false);
            esp_restart();
            return;
        }

        // Button gedrückt: Factory Reset durchführen
        if (!gpio_get_level(BTN_GPIO))
        {
            vTaskDelay(pdMS_TO_TICKS(50));

            if (!gpio_get_level(BTN_GPIO))
            {
                sys_perform_factory_reset();
                display_ui_show_factory_reset_done();
                vTaskDelay(pdMS_TO_TICKS(10000));
                gpio_power(DISPLAY_VCC_PIN, false);
                esp_restart();
            }
        }

        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ============================================================================
// FSM: STATE_SLEEP
// ============================================================================

static void state_sleep_handler(void)
{
    // Statistiken aktualisieren
    g_stats.last_sleep_duration_s = g_fsm.sleep_duration_s;

    uint64_t now_us   = rtc_now_us();
    uint64_t cycle_ms = 0;
    if (now_us >= g_boot_time_us)
    {
        cycle_ms = (now_us - g_boot_time_us) / 1000;
    }

    g_stats.last_cycle_awake_ms = (uint32_t) cycle_ms;
    g_stats.total_awake_ms += cycle_ms;
    g_stats.total_wakeups++;

    nvs_save_stats();
    sys_clear_reset_counter();
    stats_log();

    // Alles ausschalten
    ble_link_stop();
    vTaskDelay(pdMS_TO_TICKS(50));

    pump_set(false);
    gpio_power(TEMP_SENSOR_VCC_PIN, false);
    gpio_power(SOIL_VCC_PIN, false);
    gpio_power(DISPLAY_VCC_PIN, false);

    // STATE_SLEEP-Dauer vor Deep Sleep noch nachtragen
    uint64_t shutdown_now_us = esp_timer_get_time();
    if (s_state_enter_us > 0)
    {
        uint32_t shutdown_ms = (shutdown_now_us - s_state_enter_us) / 1000;
        s_cycle_state_ms[STATE_SLEEP] += shutdown_ms;
    }

    cycle_stats_log((uint32_t) cycle_ms);

    // Deep Sleep starten
    ESP_LOGI(TAG, "Deep Sleep: %lu s", (unsigned long) g_fsm.sleep_duration_s);
    esp_sleep_enable_timer_wakeup((uint64_t) g_fsm.sleep_duration_s * 1000000ULL);
    esp_deep_sleep_start();
}

// ============================================================================
// FSM: STATE_ERROR
// ============================================================================

static void state_error_handler(void)
{
    // Kein sofortiger Neustart: Bei einem dauerhaften Fehler (z.B. NVS oder I2C) würde
    // der Knoten sonst alle paar Sekunden neu starten und den Akku in Tagen leeren.
    // Stattdessen schlafen und es nach ERROR_RETRY_SLEEP_S erneut versuchen.
    ESP_LOGE(TAG, "Fehler! Neuer Versuch in %d s", ERROR_RETRY_SLEEP_S);
    g_fsm.sleep_duration_s = ERROR_RETRY_SLEEP_S;
    state_enter(STATE_SLEEP);
}

// ============================================================================
// FSM: Hauptschleife
// ============================================================================

static void run_state_machine(void)
{
    while (g_fsm.state != STATE_SLEEP)
    {
        switch (g_fsm.state)
        {
            case STATE_INIT:
                state_init_handler();
                break;

            case STATE_FIRST_SETUP:
                state_first_setup_handler();
                break;

            case STATE_MEASURE:
                state_measure_handler();
                break;

            case STATE_BLE_SEND_RECEIVE:
                state_ble_send_receive_handler();
                break;

            case STATE_IRRIGATION:
                state_irrigation_handler();
                break;

            case STATE_CALIBRATION:
                state_calibration_handler();
                break;

            case STATE_UPDATE_DISPLAY:
                state_update_display_handler();
                break;

            case STATE_FACTORY_RESET:
                state_factory_reset_handler();
                break;

            case STATE_ERROR:
                state_error_handler();
                break;

            default:
                ESP_LOGE(TAG, "Unbekannter Zustand: %d", g_fsm.state);
                state_enter(STATE_ERROR);
                break;
        }
    }

    state_sleep_handler();
}

// ============================================================================
// Einsprungpunkt
// ============================================================================

void app_main(void)
{
    memset(&g_fsm, 0, sizeof(g_fsm));
    state_enter(STATE_INIT);
    run_state_machine();

    // Sollte nie erreicht werden
    ESP_LOGE(TAG, "FATAL: Deep Sleep fehlgeschlagen!");
    esp_restart();
}