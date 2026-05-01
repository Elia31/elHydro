/**
 * @file i2c_utils.c
 * @brief I2C-Master Wrapper Implementierung
 */

#include "i2c_utils.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char* TAG = "I2C";

// ============================================================================
// Interner Zustand
// ============================================================================

static bool       s_initialized = false;
static i2c_port_t s_port        = I2C_NUM_0;
static int        s_timeout_ms  = 1000;

// ============================================================================
// Initialisierung
// ============================================================================

esp_err_t i2c_utils_init(const i2c_utils_cfg_t* cfg)
{
    if (!cfg)
    {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_initialized)
    {
        return ESP_OK;
    }

    s_port       = cfg->port;
    s_timeout_ms = (cfg->timeout_ms > 0) ? cfg->timeout_ms : 1000;

    i2c_config_t conf = { .mode             = I2C_MODE_MASTER,
                          .sda_io_num       = cfg->sda_gpio,
                          .scl_io_num       = cfg->scl_gpio,
                          .sda_pullup_en    = cfg->internal_pullups ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
                          .scl_pullup_en    = cfg->internal_pullups ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
                          .master.clk_speed = cfg->clk_hz,
                          .clk_flags        = 0 };

    esp_err_t err = i2c_param_config(s_port, &conf);
    if (err != ESP_OK)
    {
        return err;
    }

    err = i2c_driver_install(s_port, I2C_MODE_MASTER, 0, 0, 0);
    if (err != ESP_OK)
    {
        return err;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "Init OK: Port=%d, SDA=%d, SCL=%d, %lu Hz", (int) s_port, conf.sda_io_num, conf.scl_io_num, (unsigned long) cfg->clk_hz);

    return ESP_OK;
}

// ============================================================================
// Transfer-Funktionen
// ============================================================================

esp_err_t i2c_utils_write(uint8_t addr, const uint8_t* data, size_t len)
{
    if (!s_initialized)
    {
        return ESP_ERR_INVALID_STATE;
    }
    if (!data && len > 0)
    {
        return ESP_ERR_INVALID_ARG;
    }

    return i2c_master_write_to_device(s_port, addr, data, len, pdMS_TO_TICKS(s_timeout_ms));
}

esp_err_t i2c_utils_read(uint8_t addr, uint8_t* data, size_t len)
{
    if (!s_initialized)
    {
        return ESP_ERR_INVALID_STATE;
    }
    if (!data && len > 0)
    {
        return ESP_ERR_INVALID_ARG;
    }

    return i2c_master_read_from_device(s_port, addr, data, len, pdMS_TO_TICKS(s_timeout_ms));
}

esp_err_t i2c_utils_write_read(uint8_t addr, const uint8_t* wr_data, size_t wr_len, uint8_t* rd_data, size_t rd_len)
{
    if (!s_initialized)
    {
        return ESP_ERR_INVALID_STATE;
    }
    if ((!wr_data && wr_len > 0) || (!rd_data && rd_len > 0))
    {
        return ESP_ERR_INVALID_ARG;
    }

    return i2c_master_write_read_device(s_port, addr, wr_data, wr_len, rd_data, rd_len, pdMS_TO_TICKS(s_timeout_ms));
}

// ============================================================================
// Hilfsfunktionen
// ============================================================================

i2c_port_t i2c_utils_port(void)
{
    return s_port;
}

void i2c_utils_set_timeout_ms(int timeout_ms)
{
    if (timeout_ms > 0)
    {
        s_timeout_ms = timeout_ms;
    }
}