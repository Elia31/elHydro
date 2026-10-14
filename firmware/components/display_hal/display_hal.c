/**
 * @file display_hal.c
 * @brief Hardware-Abstraktionsschicht für E-Paper Displays
 */

#include "display_hal.h"
#include "config.h"
#include "font5x7.h"

#include "esp_log.h"

#include <string.h>

// ============================================================================
// Treiber Auswahl
// ============================================================================

#if USE_BW_DISPLAY
    #include "epd_bw_driver.h"
typedef epd_bw_t epd_t;
    #define epd_init          epd_bw_init
    #define epd_fill          epd_bw_fill
    #define epd_draw_pixel    epd_bw_draw_pixel
    #define epd_update        epd_bw_update
    #define epd_update_window epd_bw_update_window
    #define epd_sleep         epd_bw_sleep
    #define epd_get_width     epd_bw_get_width
    #define epd_get_height    epd_bw_get_height
    #define DISPLAY_NAME      "BW"
    #define SUPPORTS_COLOR    false
#elif USE_BWR_DISPLAY
    #include "epd_bwr_driver.h"
typedef epd_bwr_t epd_t;
    #define epd_init          epd_bwr_init
    #define epd_fill          epd_bwr_fill
    #define epd_draw_pixel    epd_bwr_draw_pixel
    #define epd_update        epd_bwr_update
    #define epd_update_window epd_bwr_update_window
    #define epd_sleep         epd_bwr_sleep
    #define epd_get_width     epd_bwr_get_width
    #define epd_get_height    epd_bwr_get_height
    #define DISPLAY_NAME      "BWR"
    #define SUPPORTS_COLOR    true
#elif USE_4COLOR_DISPLAY
    #include "epd_color_driver.h"
typedef epd_color_t epd_t;
    #define epd_init       epd_color_init
    #define epd_fill       epd_color_fill
    #define epd_draw_pixel epd_color_draw_pixel
    #define epd_update     epd_color_update
    #define epd_sleep      epd_color_sleep
    #define epd_get_width  epd_color_get_width
    #define epd_get_height epd_color_get_height
    #define DISPLAY_NAME   "4-Color"
    #define SUPPORTS_COLOR true
#else
    #error "Kein Display-Typ in config.h definiert!"
#endif

static const char* TAG = "DISPLAY";

// ============================================================================
// Interner Zustand
// ============================================================================

static epd_t                s_display;
static display_hal_config_t s_config;
static bool                 s_initialized = false;

// ============================================================================
// Farbmapping
// ============================================================================

static inline uint8_t map_color(display_color_t color)
{
#if USE_BW_DISPLAY
    // BW: Alles außer Weiß wird Schwarz
    return (color == DISPLAY_COLOR_WHITE) ? EPD_BW_WHITE : EPD_BW_BLACK;
#elif USE_BWR_DISPLAY
    // BWR: Gelb → Schwarz (kein Gelb verfügbar), Rot direkt
    switch (color)
    {
        case DISPLAY_COLOR_WHITE:
            return EPD_BWR_WHITE;
        case DISPLAY_COLOR_BLACK:
            return EPD_BWR_BLACK;
        case DISPLAY_COLOR_YELLOW:
            return EPD_BWR_BLACK; // Kein Gelb, Fallback
        case DISPLAY_COLOR_RED:
            return EPD_BWR_RED;
        default:
            return EPD_BWR_WHITE;
    }
#elif USE_4COLOR_DISPLAY
    switch (color)
    {
        case DISPLAY_COLOR_WHITE:
            return EPD_COLOR_WHITE;
        case DISPLAY_COLOR_BLACK:
            return EPD_COLOR_BLACK;
        case DISPLAY_COLOR_YELLOW:
            return EPD_COLOR_YELLOW;
        case DISPLAY_COLOR_RED:
            return EPD_COLOR_RED;
        default:
            return EPD_COLOR_WHITE;
    }
#endif
}

// ============================================================================
// Pixel-Zugriff
// ============================================================================

static inline void put_pixel(int x, int y, display_color_t color)
{
    epd_draw_pixel(&s_display, x, y, map_color(color));
}

// ============================================================================
// Text-Rendering (5x7 Font)
// ============================================================================

static void draw_char(int x, int y, char c, int scale, display_color_t color)
{
    // Ungültige Zeichen durch '?' ersetzen
    if (c < 32 || c > 126)
    {
        c = '?';
    }
    if (scale < 1)
    {
        scale = 1;
    }

    const uint8_t* glyph = font5x7[(uint8_t) c - 32];

    for (int col = 0; col < 5; col++)
    {
        uint8_t bits = glyph[col];
        for (int row = 0; row < 7; row++)
        {
            if ((bits >> row) & 0x01)
            {
                // Pixel mit Skalierung zeichnen
                for (int sx = 0; sx < scale; sx++)
                {
                    for (int sy = 0; sy < scale; sy++)
                    {
                        put_pixel(x + col * scale + sx, y + row * scale + sy, color);
                    }
                }
            }
        }
    }
}

// ============================================================================
// Initialisierung
// ============================================================================

esp_err_t display_hal_init(const display_hal_config_t* cfg)
{
    if (!cfg)
    {
        return ESP_ERR_INVALID_ARG;
    }

    if (s_initialized)
    {
        return ESP_OK;
    }

    s_config = *cfg;

    ESP_LOGI(TAG, "Init: Type=%s, UpsideDown=%s, SPI=%d Hz", DISPLAY_NAME, cfg->upside_down ? "ja" : "nein", cfg->spi_hz);

    esp_err_t ret = epd_init(&s_display,
                             cfg->spi_host,
                             cfg->pin_mosi,
                             cfg->pin_sclk,
                             cfg->pin_cs,
                             cfg->pin_dc,
                             cfg->pin_rst,
                             cfg->pin_busy,
                             cfg->spi_hz,
                             cfg->upside_down,
                             cfg->debug);

    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Initialisierung fehlgeschlagen");
        return ret;
    }

    s_initialized = true;
    ESP_LOGI(TAG, "Initialisiert (%dx%d)", epd_get_width(&s_display), epd_get_height(&s_display));

    return ESP_OK;
}

// ============================================================================
// Zeichenfunktionen
// ============================================================================

void display_hal_clear(display_color_t color)
{
    if (!s_initialized)
    {
        return;
    }
    epd_fill(&s_display, map_color(color));
}

void display_hal_draw_text(int x, int y, const char* txt, int scale, display_color_t color)
{
    if (!s_initialized || !txt)
    {
        return;
    }
    if (scale < 1)
    {
        scale = 1;
    }

    const int line_height = 7 * scale + 2;
    const int max_width   = epd_get_width(&s_display);

    int cursor_x = x;
    int cursor_y = y;

    for (const char* p = txt; *p; ++p)
    {
        if (*p == '\n')
        {
            cursor_x = x;
            cursor_y += line_height;
            continue;
        }

        draw_char(cursor_x, cursor_y, *p, scale, color);
        cursor_x += 5 * scale + 1;

        if (cursor_x >= max_width)
        {
            break;
        }
    }
}

void display_hal_draw_rect(int x, int y, int w, int h, display_color_t color)
{
    if (!s_initialized || w <= 0 || h <= 0)
    {
        return;
    }

    for (int i = 0; i < w; i++)
    {
        for (int j = 0; j < h; j++)
        {
            put_pixel(x + i, y + j, color);
        }
    }
}

void display_hal_draw_hline(int x, int y, int w, display_color_t color)
{
    if (!s_initialized || w <= 0)
    {
        return;
    }

    for (int i = 0; i < w; i++)
    {
        put_pixel(x + i, y, color);
    }
}

void display_hal_draw_vline(int x, int y, int h, display_color_t color)
{
    if (!s_initialized || h <= 0)
    {
        return;
    }

    for (int i = 0; i < h; i++)
    {
        put_pixel(x, y + i, color);
    }
}

// ============================================================================
// Display-Update
// ============================================================================

void display_hal_update(void)
{
    if (!s_initialized)
    {
        return;
    }
    if (epd_update(&s_display) != ESP_OK)
    {
        // Display reagiert nicht: für den Rest des Wachzyklus nicht mehr ansprechen,
        // sonst läuft jeder weitere Aufruf erneut in die BUSY-Timeouts
        ESP_LOGE(TAG, "Update fehlgeschlagen, Display deaktiviert");
        s_initialized = false;
    }
}

void display_hal_update_region(int x, int y, int w, int h)
{
    if (!s_initialized || w <= 0 || h <= 0)
    {
        return;
    }

#if USE_BW_DISPLAY || USE_BWR_DISPLAY
    // Clipping
    if (x < 0)
    {
        w += x;
        x = 0;
    }
    if (y < 0)
    {
        h += y;
        y = 0;
    }

    int max_w = epd_get_width(&s_display);
    int max_h = epd_get_height(&s_display);

    if (x + w > max_w)
    {
        w = max_w - x;
    }
    if (y + h > max_h)
    {
        h = max_h - y;
    }

    if (w <= 0 || h <= 0)
    {
        return;
    }

    epd_update_window(&s_display, (uint16_t) x, (uint16_t) y, (uint16_t) w, (uint16_t) h);
#elif USE_4COLOR_DISPLAY
    // 4-Color hat kein Partial Update - Fallback auf Full
    ESP_LOGW(TAG, "Partial Update nicht unterstützt, nutze Full Refresh");
    epd_update(&s_display);
#endif
}

// ============================================================================
// Stromsparmodus
// ============================================================================

void display_hal_power_off(void)
{
    if (!s_initialized)
    {
        return;
    }
    epd_sleep(&s_display);
}

// ============================================================================
// Getter
// ============================================================================

int display_hal_width(void)
{
    if (!s_initialized)
    {
        return 0;
    }
    return epd_get_width(&s_display);
}

int display_hal_height(void)
{
    if (!s_initialized)
    {
        return 0;
    }
    return epd_get_height(&s_display);
}

bool display_hal_supports_color(void)
{
    return SUPPORTS_COLOR;
}