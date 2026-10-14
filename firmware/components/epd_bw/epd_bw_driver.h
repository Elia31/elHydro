/**
 * @file epd_bw_driver.h
 * @brief Treiber für 2.9" E-Paper Display (Schwarz/Weiß)
 *
 * Unterstützt das SSD1680-basierte Display von Good Display.
 * Physische Auflösung: 128x296 Pixel, 1 Bit pro Pixel.
 *
 * https://www.good-display.com/product/389.html
 * https://www.good-display.com/companyfile/1116.html
 */

#ifndef EPD_BW_DRIVER_H
#define EPD_BW_DRIVER_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"

// ============================================================================
// Konstanten
// ============================================================================

// Physische Display-Dimensionen (unabhängig von Rotation)
#define EPD_PHYS_WIDTH  128
#define EPD_PHYS_HEIGHT 296

// Farbwerte für Framebuffer
#define EPD_BW_WHITE 0xFF
#define EPD_BW_BLACK 0x00

// ============================================================================
// Datenstruktur
// ============================================================================

typedef struct
{
    spi_device_handle_t spi;
    gpio_num_t          pin_dc;
    gpio_num_t          pin_rst;
    gpio_num_t          pin_busy;
    bool                debug;

    bool     upside_down;
    uint16_t width;  // Logische Breite (nach Rotation)
    uint16_t height; // Logische Höhe (nach Rotation)

    uint8_t* framebuffer; // 1 bpp, 8 Pixel pro Byte
} epd_bw_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert das Display
esp_err_t epd_bw_init(epd_bw_t*         epd,
                      spi_host_device_t host,
                      gpio_num_t        mosi,
                      gpio_num_t        sclk,
                      gpio_num_t        cs,
                      gpio_num_t        dc,
                      gpio_num_t        rst,
                      gpio_num_t        busy,
                      int               spi_hz,
                      bool              upside_down,
                      bool              debug);

// Füllt den Framebuffer mit einer Farbe
void epd_bw_fill(epd_bw_t* epd, uint8_t color);

// Setzt ein Pixel im Framebuffer (logische Koordinaten)
void epd_bw_draw_pixel(epd_bw_t* epd, int x, int y, uint8_t color);

// Überträgt den kompletten Framebuffer zum Display (ESP_ERR_TIMEOUT wenn das Display nicht reagiert)
esp_err_t epd_bw_update(epd_bw_t* epd);

// Partielles Update eines Bereichs (schneller, aber mit Ghosting)
void epd_bw_update_window(epd_bw_t* epd, uint16_t x, uint16_t y, uint16_t w, uint16_t h);

// Versetzt das Display in den Stromsparmodus
void epd_bw_sleep(epd_bw_t* epd);

// Gibt Ressourcen frei
void epd_bw_deinit(epd_bw_t* epd);

// ============================================================================
// Inline-Getter
// ============================================================================

static inline uint16_t epd_bw_get_width(const epd_bw_t* epd)
{
    return epd->width;
}

static inline uint16_t epd_bw_get_height(const epd_bw_t* epd)
{
    return epd->height;
}

#endif // EPD_BW_DRIVER_H