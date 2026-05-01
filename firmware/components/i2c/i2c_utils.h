/**
 * @file i2c_utils.h
 * @brief I2C-Master Wrapper für vereinfachte Kommunikation
 */

#ifndef I2C_UTILS_H
#define I2C_UTILS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c.h"
#include "esp_err.h"

// ============================================================================
// Konfiguration
// ============================================================================

typedef struct
{
    i2c_port_t port; // I2C-Port (z.B. I2C_NUM_0)
    int        sda_gpio;
    int        scl_gpio;
    uint32_t   clk_hz; // Taktfrequenz in Hz
    int        timeout_ms;
    bool       internal_pullups;
} i2c_utils_cfg_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert den I2C-Bus (idempotent, mehrfacher Aufruf OK)
esp_err_t i2c_utils_init(const i2c_utils_cfg_t* cfg);

// Einfache Transfers
esp_err_t i2c_utils_write(uint8_t addr, const uint8_t* data, size_t len);
esp_err_t i2c_utils_read(uint8_t addr, uint8_t* data, size_t len);

// Write + Read in einem Vorgang (für Registerzugriffe)
esp_err_t i2c_utils_write_read(uint8_t addr, const uint8_t* wr_data, size_t wr_len, uint8_t* rd_data, size_t rd_len);

// Hilfsfunktionen
i2c_port_t i2c_utils_port(void);
void       i2c_utils_set_timeout_ms(int timeout_ms);

#endif // I2C_UTILS_H