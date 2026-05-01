/**
 * @file epd_color_driver.h
 * @brief Treiber für 2.9" E-Paper Display (4-Farben)
 *
 * Unterstützt das JD79661-basierte Display von Good Display.
 * Physische Auflösung: 128x296 Pixel, 2 Bit pro Pixel.
 * Farben: Schwarz, Weiß, Gelb, Rot.
 * 
 * https://www.good-display.com/product/742.html
 * https://www.good-display.com/companyfile/1809.html
 */

#ifndef EPD_COLOR_DRIVER_H
#define EPD_COLOR_DRIVER_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"

// ============================================================================
// Konstanten
// ============================================================================

// Physische Display-Dimensionen (unabhängig von Rotation)
#define EPD_COLOR_PHYS_WIDTH  128
#define EPD_COLOR_PHYS_HEIGHT 296

// Farbwerte (2bpp Encoding: 4 Pixel pro Byte)
#define EPD_COLOR_BLACK  0x00
#define EPD_COLOR_WHITE  0x01
#define EPD_COLOR_YELLOW 0x02
#define EPD_COLOR_RED    0x03

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

    uint8_t* framebuffer; // 2 bpp, 4 Pixel pro Byte
    uint32_t fb_size;
} epd_color_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert das Display
esp_err_t epd_color_init(epd_color_t*      epd,
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
void epd_color_fill(epd_color_t* epd, uint8_t color);

// Setzt ein Pixel im Framebuffer (logische Koordinaten)
void epd_color_draw_pixel(epd_color_t* epd, int x, int y, uint8_t color);

// Überträgt den kompletten Framebuffer zum Display
void epd_color_update(epd_color_t* epd);

// Versetzt das Display in den Stromsparmodus
void epd_color_sleep(epd_color_t* epd);

// Gibt Ressourcen frei
void epd_color_deinit(epd_color_t* epd);

// ============================================================================
// Inline-Getter
// ============================================================================

static inline uint16_t epd_color_get_width(const epd_color_t* epd)
{
    return epd->width;
}

static inline uint16_t epd_color_get_height(const epd_color_t* epd)
{
    return epd->height;
}

#endif // EPD_COLOR_DRIVER_H