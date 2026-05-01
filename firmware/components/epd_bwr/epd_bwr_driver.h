/**
 * @file epd_bwr_driver.h
 * @brief Treiber für 2.9" E-Paper Display (Schwarz/Weiß/Rot)
 *
 * Unterstützt das SSD1680-basierte 3-Farb-Display von Good Display.
 * Physische Auflösung: 128x296 Pixel, 2 separate RAM-Ebenen (BW + RED).
 *
 * https://www.good-display.com/product/527.html
 * https://www.good-display.com/companyfile/1390.html
 */

#ifndef EPD_BWR_DRIVER_H
#define EPD_BWR_DRIVER_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"

// ============================================================================
// Konstanten
// ============================================================================

// Physische Display-Dimensionen (unabhängig von Rotation)
#define EPD_BWR_PHYS_WIDTH  128
#define EPD_BWR_PHYS_HEIGHT 296

// Farbwerte (logisch, für draw_pixel)
#define EPD_BWR_WHITE 0
#define EPD_BWR_BLACK 1
#define EPD_BWR_RED   2

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

    uint8_t* framebuffer_bw;  // RAM1 (0x24): Schwarz/Weiß, 1 bpp
    uint8_t* framebuffer_red; // RAM2 (0x26): Rot-Ebene, 1 bpp
} epd_bwr_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert das Display
esp_err_t epd_bwr_init(epd_bwr_t*        epd,
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

// Füllt beide Framebuffer mit einer Farbe
void epd_bwr_fill(epd_bwr_t* epd, uint8_t color);

// Setzt ein Pixel im Framebuffer (logische Koordinaten)
void epd_bwr_draw_pixel(epd_bwr_t* epd, int x, int y, uint8_t color);

// Überträgt beide Framebuffer zum Display (vollständiges Update)
void epd_bwr_update(epd_bwr_t* epd);

// Partielles Update eines Bereichs
void epd_bwr_update_window(epd_bwr_t* epd, uint16_t x, uint16_t y, uint16_t w, uint16_t h);

// Versetzt das Display in den Stromsparmodus
void epd_bwr_sleep(epd_bwr_t* epd);

// Gibt Ressourcen frei
void epd_bwr_deinit(epd_bwr_t* epd);

// ============================================================================
// Inline-Getter
// ============================================================================

static inline uint16_t epd_bwr_get_width(const epd_bwr_t* epd)
{
    return epd->width;
}

static inline uint16_t epd_bwr_get_height(const epd_bwr_t* epd)
{
    return epd->height;
}

#endif // EPD_BWR_DRIVER_H
