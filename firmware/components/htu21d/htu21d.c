/**
 * @file htu21d.c
 * @brief Treiber für HTU21D Temperatur- und Feuchtigkeitssensor
 */

#include "htu21d.h"
#include "i2c_utils.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char* TAG = "HTU21D";

// ============================================================================
// Konstanten
// ============================================================================

#define HTU21D_ADDR 0x40

// Befehle (No Hold Master Mode)
#define CMD_TRIGGER_TEMP     0xF3
#define CMD_TRIGGER_HUMIDITY 0xF5
#define CMD_READ_USER_REG    0xE7

// Messzeiten laut Datenblatt
#define TEMP_MEASURE_TIME_MS 60 // max. 50ms laut Datenblatt + Puffer
#define RH_MEASURE_TIME_MS   20 // max. 16ms laut Datenblatt + Puffer

// ============================================================================
// Initialisierung (dummye Prüfung ob Sensor antwortet)
// ============================================================================

esp_err_t htu21d_init(void)
{
    uint8_t cmd = CMD_READ_USER_REG;
    uint8_t reg = 0;

    esp_err_t err = i2c_utils_write_read(HTU21D_ADDR, &cmd, 1, &reg, 1);
    if (err == ESP_OK)
    {
        ESP_LOGI(TAG, "Sensor erkannt, User-Register=0x%02X", reg);
    }
    else
    {
        ESP_LOGE(TAG, "Sensor nicht gefunden: %s", esp_err_to_name(err));
    }

    return err;
}

// ============================================================================
// Messungen
// ============================================================================

esp_err_t htu21d_read_temperature(float* temp_c)
{
    if (!temp_c)
    {
        return ESP_ERR_INVALID_ARG;
    }

    uint8_t   cmd = CMD_TRIGGER_TEMP;
    esp_err_t err = i2c_utils_write(HTU21D_ADDR, &cmd, 1);
    if (err != ESP_OK)
    {
        return err;
    }

    vTaskDelay(pdMS_TO_TICKS(TEMP_MEASURE_TIME_MS));

    uint8_t buf[3] = { 0 };
    err            = i2c_utils_read(HTU21D_ADDR, buf, 3);
    if (err != ESP_OK)
    {
        return err;
    }

    // Rohwert aus den ersten beiden Bytes (untere 2 Bits sind Status)
    uint16_t raw = ((uint16_t) buf[0] << 8) | (buf[1] & 0xFC);

    // Umrechnung laut Datenblatt
    *temp_c = -46.85f + (175.72f * (float) raw / 65536.0f);

    return ESP_OK;
}

esp_err_t htu21d_read_humidity(float* rh_pct)
{
    if (!rh_pct)
    {
        return ESP_ERR_INVALID_ARG;
    }

    uint8_t   cmd = CMD_TRIGGER_HUMIDITY;
    esp_err_t err = i2c_utils_write(HTU21D_ADDR, &cmd, 1);
    if (err != ESP_OK)
    {
        return err;
    }

    vTaskDelay(pdMS_TO_TICKS(RH_MEASURE_TIME_MS));

    uint8_t buf[3] = { 0 };
    err            = i2c_utils_read(HTU21D_ADDR, buf, 3);
    if (err != ESP_OK)
    {
        return err;
    }

    // Rohwert aus den ersten beiden Bytes (untere 2 Bits sind Status)
    uint16_t raw = ((uint16_t) buf[0] << 8) | (buf[1] & 0xFC);

    // Umrechnung laut Datenblatt
    float rh = -6.0f + (125.0f * (float) raw / 65536.0f);

    // Auf gültigen Bereich begrenzen
    if (rh < 0.0f)
    {
        rh = 0.0f;
    }
    else if (rh > 100.0f)
    {
        rh = 100.0f;
    }

    *rh_pct = rh;

    return ESP_OK;
}