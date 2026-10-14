/**
 * @file display_hal.h
 * @brief Hardware-Abstraktionsschicht für E-Paper Displays
 *
 * Unterstützt sowohl Schwarz/Weiß (SSD1680) und Schwarz/Weiß/Rot (SSD1680) als auch
 * 4-Farben Displays (JD79661) über eine einheitliche API.
 */

#ifndef DISPLAY_HAL_H
#define DISPLAY_HAL_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/spi_master.h"
#include "esp_err.h"

// ============================================================================
// Farben
// ============================================================================

// Bei BW-Display werden Gelb und Rot automatisch zu Schwarz gemappt
typedef enum
{
    DISPLAY_COLOR_WHITE  = 0,
    DISPLAY_COLOR_BLACK  = 1,
    DISPLAY_COLOR_YELLOW = 2,
    DISPLAY_COLOR_RED    = 3
} display_color_t;

// ============================================================================
// Konfiguration
// ============================================================================

typedef struct
{
    spi_host_device_t spi_host;
    int               pin_mosi;
    int               pin_sclk;
    int               pin_cs;
    int               pin_dc;
    int               pin_rst;
    int               pin_busy;
    int               spi_hz;
    bool              upside_down;
    bool              debug;
} display_hal_config_t;

// ============================================================================
// Funktionen
// ============================================================================

// Initialisiert das Display mit der angegebenen Konfiguration
esp_err_t display_hal_init(const display_hal_config_t* cfg);

// Füllt das gesamte Display mit einer Farbe
void display_hal_clear(display_color_t color);

// Zeichnet Text an Position (x,y) mit Skalierung
void display_hal_draw_text(int x, int y, const char* text, int scale, display_color_t color);

// Zeichnet ein gefülltes Rechteck
void display_hal_draw_rect(int x, int y, int w, int h, display_color_t color);

// Zeichnet eine horizontale Linie
void display_hal_draw_hline(int x, int y, int w, display_color_t color);

// Zeichnet eine vertikale Linie
void display_hal_draw_vline(int x, int y, int h, display_color_t color);

// Überträgt den Framebuffer zum Display (Full Refresh).
// Reagiert das Display nicht, wird es bis zum nächsten Init deaktiviert.
void display_hal_update(void);

// Partielles Update eines Bereichs (nur BW, bei 4-Color Fallback auf Full)
void display_hal_update_region(int x, int y, int w, int h);

// Versetzt das Display in den Stromsparmodus
void display_hal_power_off(void);

// Gibt die aktuelle Display-Breite zurück (abhängig von Rotation)
int display_hal_width(void);

// Gibt die aktuelle Display-Höhe zurück (abhängig von Rotation)
int display_hal_height(void);

// Gibt true zurück, wenn das Display Farben darstellen kann (BWR oder 4-Farben)
bool display_hal_supports_color(void);

#endif // DISPLAY_HAL_H