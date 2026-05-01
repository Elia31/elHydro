/**
 * @file display_ui.c
 * @brief UI-Komponenten für das E-Paper Display
 */

#include "display_ui.h"

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "config.h"

// ============================================================================
// Konstanten
// ============================================================================

#define FONT_HEIGHT  7
#define FONT_WIDTH   5
#define CHAR_SPACING 1

// ============================================================================
// Hilfsfunktionen
// ============================================================================

// Zeichnet Text rechtsbündig
static void draw_text_right(int right_x, int y, const char* text, int scale, display_color_t color)
{
    int text_width = (int) strlen(text) * (FONT_WIDTH * scale + CHAR_SPACING);
    int x          = right_x - text_width;
    if (x < 0)
    {
        x = 0;
    }
    display_hal_draw_text(x, y, text, scale, color);
}

// Formatiert Unix-Zeitstempel als "HH:MM DD.MM.YYYY" (Lokalzeit via TIMEZONE_OFFSET_S)
static void format_datetime(uint32_t unix_time, char* buf, size_t buf_size)
{
    if (unix_time == 0)
    {
        snprintf(buf, buf_size, "--:-- --.--.----");
        return;
    }

    time_t     t       = (time_t) unix_time + TIMEZONE_OFFSET_S;
    struct tm* tm_info = gmtime(&t);
    strftime(buf, buf_size, "%H:%M %d.%m.%Y", tm_info);
}

// Formatiert eine Zeitdauer als lesbaren String
static void format_duration(uint32_t seconds, char* buf, size_t buf_size)
{
    if (seconds < 90)
    {
        snprintf(buf, buf_size, "%lusec", (unsigned long) seconds);
    }
    else if (seconds < 3600)
    {
        snprintf(buf, buf_size, "%lumin", (unsigned long) (seconds / 60));
    }
    else
    {
        unsigned h = seconds / 3600;
        unsigned m = (seconds % 3600) / 60;
        if (m > 0)
        {
            snprintf(buf, buf_size, "%uh%umin", h, m);
        }
        else
        {
            snprintf(buf, buf_size, "%uh", h);
        }
    }
}

// Bestimmt die Farbe basierend auf der Abweichung vom Zielwert
static display_color_t get_soil_color(int current, int target)
{
    int delta     = current - target;
    int abs_delta = (delta < 0) ? -delta : delta;

    if (abs_delta <= DELTA_THRESHOLD_OK)
    {
        return DISPLAY_COLOR_BLACK;
    }
    else if (abs_delta <= DELTA_THRESHOLD_WARN)
    {
        return DISPLAY_COLOR_YELLOW;
    }
    else
    {
        return DISPLAY_COLOR_RED;
    }
}

// ============================================================================
// Initialisierung
// ============================================================================

esp_err_t display_ui_init(const display_hal_config_t* cfg)
{
    return display_hal_init(cfg);
}

// ============================================================================
// Setup-Screen (Ersteinrichtung)
// ============================================================================

void display_ui_show_setup_screen(void)
{
    const int width  = display_hal_width();
    const int height = display_hal_height();
    const int margin = 6;

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel zentriert
    const char* title   = "ElHydro";
    int         title_w = (int) strlen(title) * (FONT_WIDTH + CHAR_SPACING);
    int         title_x = (width - title_w) / 2;
    int         title_y = 10;

    display_hal_draw_text(title_x, title_y, title, 1, DISPLAY_COLOR_BLACK);
    display_hal_draw_hline(margin, title_y + FONT_HEIGHT + 3, width - 2 * margin, DISPLAY_COLOR_BLACK);

    // Hauptkarte mit Rahmen
    const int card_x = margin;
    const int card_y = 28;
    const int card_w = width - 2 * margin;
    const int card_h = height - card_y - margin;

    display_hal_draw_hline(card_x, card_y, card_w, DISPLAY_COLOR_BLACK);
    display_hal_draw_hline(card_x, card_y + card_h - 1, card_w, DISPLAY_COLOR_BLACK);
    display_hal_draw_vline(card_x, card_y, card_h, DISPLAY_COLOR_BLACK);
    display_hal_draw_vline(card_x + card_w - 1, card_y, card_h, DISPLAY_COLOR_BLACK);

    // Haupttext zentriert in Karte
    const char* msg   = "Verbinde per Bluetooth";
    int         msg_w = (int) strlen(msg) * (FONT_WIDTH * 2 + CHAR_SPACING);
    int         msg_h = FONT_HEIGHT * 2;
    int         msg_x = card_x + (card_w - msg_w) / 2;
    int         msg_y = card_y + (card_h - msg_h) / 2 - 6;

    display_hal_draw_text(msg_x, msg_y, msg, 2, DISPLAY_COLOR_RED);

    // Fußzeile
    const char* footer   = "Noch nicht eingerichtet";
    int         footer_w = (int) strlen(footer) * (FONT_WIDTH + CHAR_SPACING);
    int         footer_x = card_x + (card_w - footer_w) / 2;
    int         footer_y = card_y + card_h - 14;

    display_hal_draw_text(footer_x, footer_y, footer, 1, DISPLAY_COLOR_RED);

    display_hal_update();
}

// ============================================================================
// Normal-Screen (Hauptanzeige)
// ============================================================================

void display_ui_show_normal_screen(const display_ui_data_t* data)
{
    if (!data)
    {
        return;
    }

    const int width  = display_hal_width();
    const int margin = 4;
    int       y      = 4;
    char      buf[64];

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Zeile 1: Temperatur links, Luftfeuchtigkeit rechts
    if (isfinite(data->temp_c))
    {
        snprintf(buf, sizeof(buf), "Temperatur: %.1foC", data->temp_c);
    }
    else
    {
        snprintf(buf, sizeof(buf), "Temperatur: --.-oC");
    }
    display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);

    if (isfinite(data->rh_pct))
    {
        snprintf(buf, sizeof(buf), "Luftfeuchtigkeit: %.0f%%", roundf(data->rh_pct));
    }
    else
    {
        snprintf(buf, sizeof(buf), "Luftfeuchtigkeit: --%%");
    }
    draw_text_right(width - margin, y, buf, 1, DISPLAY_COLOR_BLACK);

    y += 12;
    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 4;

    // Farbe für Bodenfeuchte bestimmen
    display_color_t soil_color = get_soil_color(data->soil_pct, data->target_soil_pct);
    int             delta      = data->soil_pct - data->target_soil_pct;

    // Zeile 2: Bodenfeuchte groß und zentriert
    snprintf(buf, sizeof(buf), "BODEN: %d%%", data->soil_pct);
    int text_w   = (int) strlen(buf) * (FONT_WIDTH * 2 + CHAR_SPACING);
    int center_x = (width - text_w) / 2;

    display_hal_draw_text(center_x, y, buf, 2, soil_color);
    y += FONT_HEIGHT * 2 + 6;

    // Zeile 3: Zielwert links, Delta rechts
    snprintf(buf, sizeof(buf), "Target: %d%%", data->target_soil_pct);
    display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);

    snprintf(buf, sizeof(buf), "Delta: %+d%%", delta);
    draw_text_right(width - margin, y, buf, 1, soil_color);

    y += 10;

    // Fortschrittsbalken mit Zielmarkierung
    const int bar_x = margin;
    const int bar_w = width - 2 * margin;
    const int bar_h = 8;

    // Rahmen
    display_hal_draw_hline(bar_x, y, bar_w, DISPLAY_COLOR_BLACK);
    display_hal_draw_hline(bar_x, y + bar_h, bar_w, DISPLAY_COLOR_BLACK);
    display_hal_draw_vline(bar_x, y, bar_h + 1, DISPLAY_COLOR_BLACK);
    display_hal_draw_vline(bar_x + bar_w - 1, y, bar_h + 1, DISPLAY_COLOR_BLACK);

    // Füllung
    int fill_w = ((bar_w - 4) * data->soil_pct) / 100;
    if (fill_w > bar_w - 4)
    {
        fill_w = bar_w - 4;
    }
    if (fill_w > 0)
    {
        display_hal_draw_rect(bar_x + 2, y + 2, fill_w, bar_h - 3, soil_color);
    }

    // Zielmarkierung (kleines Dreieck unter dem Balken)
    int marker_x = bar_x + 2 + ((bar_w - 4) * data->target_soil_pct) / 100;
    if (marker_x >= bar_x && marker_x < bar_x + bar_w)
    {
        for (int i = 0; i < 3; i++)
        {
            display_hal_draw_hline(marker_x - i, y + bar_h + 2 + i, 2 * i + 1, DISPLAY_COLOR_BLACK);
        }
    }

    y += bar_h + 8;
    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 4;

    // Zeile 4: Zeitstempel
    if (data->time_valid)
    {
        char time_str[32];

        format_datetime(data->last_measurement_unix, time_str, sizeof(time_str));
        snprintf(buf, sizeof(buf), "Letzte Messung:   %s", time_str);
        display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);
        y += 9;

        format_datetime(data->next_measurement_unix, time_str, sizeof(time_str));
        snprintf(buf, sizeof(buf), "Naechste Messung: %s", time_str);
        display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);

        // Relative Zeitangabe rechts
        if (data->sleep_duration_s > 0)
        {
            char duration[24];
            format_duration(data->sleep_duration_s, duration, sizeof(duration));
            snprintf(buf, sizeof(buf), "(in %s)", duration);
            draw_text_right(width - margin, y, buf, 1, DISPLAY_COLOR_BLACK);
        }
        y += 10;
    }
    else
    {
        // Zeit nicht synchronisiert
        if (data->sleep_duration_s > 0)
        {
            char duration[24];
            format_duration(data->sleep_duration_s, duration, sizeof(duration));
            snprintf(buf, sizeof(buf), "Naechste Messung in: %s", duration);
            display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);
            y += 10;
        }

        display_hal_draw_text(margin, y, "Zeit: Nicht sync", 1, DISPLAY_COLOR_BLACK);
        y += 10;
    }

    // Debug-Informationen
    snprintf(buf, sizeof(buf), "Sensor raw:%d", data->soil_raw);
    display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);

    snprintf(buf, sizeof(buf), "Kalibration dry:%d  wet:%d", data->calib_raw_dry, data->calib_raw_wet);
    draw_text_right(width - margin, y, buf, 1, DISPLAY_COLOR_BLACK);
    y += 9;

    snprintf(buf, sizeof(buf), "Messungs ID:#%lu", (unsigned long) data->measurement_id);
    display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);
    // Letzte Bewässerungsdauer rechts
    char irr_buf[24];
    if (data->last_irrigation_ms > 0)
    {
        // Wenn gegossen wurde: Zeit in Sekunden
        float duration_s = data->last_irrigation_ms / 1000.0f;
        snprintf(irr_buf, sizeof(irr_buf), "Gegossen: %.1fs", duration_s);
    }
    else
    {
        // Wenn nicht gegossen wurde: Explizit 0s anzeigen
        snprintf(irr_buf, sizeof(irr_buf), "Gegossen: 0s");
    }

    draw_text_right(width - margin, y, irr_buf, 1, DISPLAY_COLOR_BLACK);
    y += 9;

    // Statistiken
    if (isfinite(data->avg_awake_s) && data->avg_awake_s >= 0.0f && data->total_wakeups > 0)
    {
        snprintf(buf, sizeof(buf), "Avg. Awake: %.1fs | BLE Success: %.0f%%", data->avg_awake_s, data->ble_success_pct);
    }
    else
    {
        snprintf(buf, sizeof(buf), "BLE Success: %.0f%%", data->ble_success_pct);
    }
    display_hal_draw_text(margin, y, buf, 1, DISPLAY_COLOR_BLACK);
    y += 9;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 4;

    // Statuszeile: Buffer, Batterie, BLE
    const int char_w = FONT_WIDTH + CHAR_SPACING;

    char status_left[24];
    snprintf(status_left, sizeof(status_left), "Buffer:%d", data->buffer_count);

    char status_mid[16];
    if (data->battery_voltage < 0.1f)
    {
        snprintf(status_mid, sizeof(status_mid), "Bat:--V");
    }
    else
    {
        snprintf(status_mid, sizeof(status_mid), "Bat:%.1fV", data->battery_voltage);
    }

    const char* status_right = data->ble_connected ? "[BT]" : "[ - ]";

    int w_left  = (int) strlen(status_left) * char_w;
    int w_mid   = (int) strlen(status_mid) * char_w;
    int w_right = (int) strlen(status_right) * char_w;

    int x_left  = margin;
    int x_right = width - margin - w_right;
    int x_mid   = (width - w_mid) / 2;

    // Kollisionsvermeidung
    if (x_mid < x_left + w_left + 1)
    {
        x_mid = x_left + w_left + 1;
    }
    if (x_mid + w_mid > x_right - 1)
    {
        x_mid = x_right - 1 - w_mid;
    }

    display_color_t buf_color = (data->buffer_count > 0) ? DISPLAY_COLOR_RED : DISPLAY_COLOR_BLACK;
    display_color_t ble_color = data->ble_connected ? DISPLAY_COLOR_BLACK : DISPLAY_COLOR_RED;

    display_hal_draw_text(x_left, y, status_left, 1, buf_color);
    display_hal_draw_text(x_mid, y, status_mid, 1, DISPLAY_COLOR_BLACK);
    draw_text_right(width - margin, y, status_right, 1, ble_color);

    display_hal_update();
}

// ============================================================================
// Kalibrierungs-Screens
// ============================================================================

void display_ui_show_calibration_step1(void)
{
    const int width  = display_hal_width();
    const int margin = 6;
    int       y      = 10;

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel zentriert
    const char* title   = "KALIBRIERUNG";
    int         title_w = (int) strlen(title) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - title_w) / 2, y, title, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 8;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 6;

    display_hal_draw_text(margin, y, "Schritt 1/2:", 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 6;

    display_hal_draw_text(margin, y, "1. Sensor abtrocknen", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 4;

    display_hal_draw_text(margin, y, "2. In Luft halten", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 8;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 6;

    display_hal_draw_text(margin, y, "Boot-Taste", 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 2;

    display_hal_draw_text(margin, y, "druecken wenn bereit", 2, DISPLAY_COLOR_BLACK);

    display_hal_update();
}

void display_ui_show_calibration_step2(void)
{
    const int width  = display_hal_width();
    const int margin = 6;
    int       y      = 10;

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel zentriert
    const char* title   = "KALIBRIERUNG";
    int         title_w = (int) strlen(title) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - title_w) / 2, y, title, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 8;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 6;

    display_hal_draw_text(margin, y, "Schritt 2/2:", 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 6;

    display_hal_draw_text(margin, y, "Sensor komplett", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 4;

    display_hal_draw_text(margin, y, "in Wasser tauchen", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 8;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 6;

    display_hal_draw_text(margin, y, "Boot-Taste", 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 2;

    display_hal_draw_text(margin, y, "druecken wenn bereit", 2, DISPLAY_COLOR_BLACK);

    display_hal_update();
}

void display_ui_show_calibration_success(int raw_dry, int raw_wet)
{
    const int width  = display_hal_width();
    const int margin = 6;
    int       y      = 6;
    char      buf[32];

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel
    const char* title   = "KALIBRIERUNG";
    int         title_w = (int) strlen(title) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - title_w) / 2, y, title, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 4;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 3;

    // Erfolgsmeldung
    const char* success   = "ERFOLGREICH!";
    int         success_w = (int) strlen(success) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - success_w) / 2, y, success, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 6;

    // Kalibrierungswerte
    snprintf(buf, sizeof(buf), "Trocken: %d", raw_dry);
    display_hal_draw_text(margin, y, buf, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 3;

    snprintf(buf, sizeof(buf), "Nass:    %d", raw_wet);
    display_hal_draw_text(margin, y, buf, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 6;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 3;

    display_hal_draw_text(margin, y, "Werte gespeichert", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 3;

    display_hal_draw_text(margin, y, "Boot-Taste", 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 2;

    display_hal_draw_text(margin, y, "druecken zum Starten", 2, DISPLAY_COLOR_BLACK);

    display_hal_update();
}

void display_ui_show_calibration_timeout(void)
{
    const int width  = display_hal_width();
    const int margin = 6;
    int       y      = 20;

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel
    const char* title   = "KALIBRIERUNG";
    int         title_w = (int) strlen(title) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - title_w) / 2, y, title, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 8;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 10;

    // Timeout-Meldung
    const char* timeout_msg = "TIMEOUT";
    int         timeout_w   = (int) strlen(timeout_msg) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - timeout_w) / 2, y, timeout_msg, 2, DISPLAY_COLOR_RED);
    y += FONT_HEIGHT * 2 + 10;

    display_hal_draw_text(margin, y, "Kalibrierung", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 4;

    display_hal_draw_text(margin, y, "uebersprungen", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 10;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 6;

    display_hal_draw_text(margin, y, "Alte Werte behalten", 1, DISPLAY_COLOR_BLACK);

    display_hal_update();
}

// ============================================================================
// Werksreset-Screens
// ============================================================================

void display_ui_show_factory_reset_confirm(void)
{
    const int width  = display_hal_width();
    const int margin = 6;
    int       y      = 4;

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel
    const char* title   = "WERKSRESET";
    int         title_w = (int) strlen(title) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - title_w) / 2, y, title, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 4;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 4;

    display_hal_draw_text(margin, y, "Reset ausloesen?", 1, DISPLAY_COLOR_RED);
    y += FONT_HEIGHT + 4;

    display_hal_draw_text(margin, y, "3x Reset-Taste gedrueckt.", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 2;

    display_hal_draw_text(margin, y, "Alle Einstellungen und", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 2;

    display_hal_draw_text(margin, y, "Messwerte werden geloescht.", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 4;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 6;

    display_hal_draw_text(margin, y, "Boot-Taste = JA", 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 4;

    display_hal_draw_text(margin, y, "Warten = Abbrechen", 2, DISPLAY_COLOR_BLACK);

    display_hal_update();
}

void display_ui_show_factory_reset_done(void)
{
    const int width  = display_hal_width();
    const int margin = 6;
    int       y      = 20;

    display_hal_clear(DISPLAY_COLOR_WHITE);

    // Titel
    const char* title   = "WERKSRESET";
    int         title_w = (int) strlen(title) * (FONT_WIDTH * 2 + CHAR_SPACING);
    display_hal_draw_text((width - title_w) / 2, y, title, 2, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT * 2 + 10;

    display_hal_draw_hline(margin, y, width - 2 * margin, DISPLAY_COLOR_BLACK);
    y += 10;

    const char* msg1   = "WERKSEINSTELLUNGEN";
    int         msg1_w = (int) strlen(msg1) * (FONT_WIDTH + CHAR_SPACING);
    display_hal_draw_text((width - msg1_w) / 2, y, msg1, 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 4;

    const char* msg2   = "WURDEN WIEDERHERGESTELLT";
    int         msg2_w = (int) strlen(msg2) * (FONT_WIDTH + CHAR_SPACING);
    display_hal_draw_text((width - msg2_w) / 2, y, msg2, 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 10;

    display_hal_draw_text(margin, y, "Bitte erneut per PC", 1, DISPLAY_COLOR_BLACK);
    y += FONT_HEIGHT + 2;

    display_hal_draw_text(margin, y, "einrichten.", 1, DISPLAY_COLOR_BLACK);

    display_hal_update();
}