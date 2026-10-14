#!/usr/bin/env python3
"""
elHydro E-Paper Display Simulator
Pixelgenaue Simulation des 2.9" E-Paper Displays (296x128, 4-Color)

Steuerung:
  Fenster: Pfeiltasten Links/Rechts = Screen wechseln, ESC = Beenden
  Terminal: Befehle eingeben (z.B. 'soil 80', 'temp 25', 'help' für alle)
"""

import math
import time as time_mod
import tkinter as tk
from datetime import datetime, timezone

# ============================================================================
# Font 5x7 (identisch zu firmware font5x7.c)
# ============================================================================

FONT5X7 = [
    [0x00, 0x00, 0x00, 0x00, 0x00],  # ' '
    [0x00, 0x00, 0x5F, 0x00, 0x00],  # '!'
    [0x00, 0x07, 0x00, 0x07, 0x00],  # '"'
    [0x14, 0x7F, 0x14, 0x7F, 0x14],  # '#'
    [0x24, 0x2A, 0x7F, 0x2A, 0x12],  # '$'
    [0x23, 0x13, 0x08, 0x64, 0x62],  # '%'
    [0x36, 0x49, 0x55, 0x22, 0x50],  # '&'
    [0x00, 0x05, 0x03, 0x00, 0x00],  # "'"
    [0x00, 0x1C, 0x22, 0x41, 0x00],  # '('
    [0x00, 0x41, 0x22, 0x1C, 0x00],  # ')'
    [0x14, 0x08, 0x3E, 0x08, 0x14],  # '*'
    [0x08, 0x08, 0x3E, 0x08, 0x08],  # '+'
    [0x00, 0x50, 0x30, 0x00, 0x00],  # ','
    [0x08, 0x08, 0x08, 0x08, 0x08],  # '-'
    [0x00, 0x60, 0x60, 0x00, 0x00],  # '.'
    [0x20, 0x10, 0x08, 0x04, 0x02],  # '/'
    [0x3E, 0x51, 0x49, 0x45, 0x3E],  # '0'
    [0x00, 0x42, 0x7F, 0x40, 0x00],  # '1'
    [0x42, 0x61, 0x51, 0x49, 0x46],  # '2'
    [0x21, 0x41, 0x45, 0x4B, 0x31],  # '3'
    [0x18, 0x14, 0x12, 0x7F, 0x10],  # '4'
    [0x27, 0x45, 0x45, 0x45, 0x39],  # '5'
    [0x3C, 0x4A, 0x49, 0x49, 0x30],  # '6'
    [0x01, 0x71, 0x09, 0x05, 0x03],  # '7'
    [0x36, 0x49, 0x49, 0x49, 0x36],  # '8'
    [0x06, 0x49, 0x49, 0x29, 0x1E],  # '9'
    [0x00, 0x36, 0x36, 0x00, 0x00],  # ':'
    [0x00, 0x56, 0x36, 0x00, 0x00],  # ';'
    [0x08, 0x14, 0x22, 0x41, 0x00],  # '<'
    [0x14, 0x14, 0x14, 0x14, 0x14],  # '='
    [0x00, 0x41, 0x22, 0x14, 0x08],  # '>'
    [0x02, 0x01, 0x51, 0x09, 0x06],  # '?'
    [0x32, 0x49, 0x79, 0x41, 0x3E],  # '@'
    [0x7E, 0x11, 0x11, 0x11, 0x7E],  # 'A'
    [0x7F, 0x49, 0x49, 0x49, 0x36],  # 'B'
    [0x3E, 0x41, 0x41, 0x41, 0x22],  # 'C'
    [0x7F, 0x41, 0x41, 0x22, 0x1C],  # 'D'
    [0x7F, 0x49, 0x49, 0x49, 0x41],  # 'E'
    [0x7F, 0x09, 0x09, 0x09, 0x01],  # 'F'
    [0x3E, 0x41, 0x49, 0x49, 0x7A],  # 'G'
    [0x7F, 0x08, 0x08, 0x08, 0x7F],  # 'H'
    [0x00, 0x41, 0x7F, 0x41, 0x00],  # 'I'
    [0x20, 0x40, 0x41, 0x3F, 0x01],  # 'J'
    [0x7F, 0x08, 0x14, 0x22, 0x41],  # 'K'
    [0x7F, 0x40, 0x40, 0x40, 0x40],  # 'L'
    [0x7F, 0x02, 0x0C, 0x02, 0x7F],  # 'M'
    [0x7F, 0x04, 0x08, 0x10, 0x7F],  # 'N'
    [0x3E, 0x41, 0x41, 0x41, 0x3E],  # 'O'
    [0x7F, 0x09, 0x09, 0x09, 0x06],  # 'P'
    [0x3E, 0x41, 0x51, 0x21, 0x5E],  # 'Q'
    [0x7F, 0x09, 0x19, 0x29, 0x46],  # 'R'
    [0x46, 0x49, 0x49, 0x49, 0x31],  # 'S'
    [0x01, 0x01, 0x7F, 0x01, 0x01],  # 'T'
    [0x3F, 0x40, 0x40, 0x40, 0x3F],  # 'U'
    [0x1F, 0x20, 0x40, 0x20, 0x1F],  # 'V'
    [0x3F, 0x40, 0x38, 0x40, 0x3F],  # 'W'
    [0x63, 0x14, 0x08, 0x14, 0x63],  # 'X'
    [0x07, 0x08, 0x70, 0x08, 0x07],  # 'Y'
    [0x61, 0x51, 0x49, 0x45, 0x43],  # 'Z'
    [0x00, 0x7F, 0x41, 0x41, 0x00],  # '['
    [0x02, 0x04, 0x08, 0x10, 0x20],  # '\'
    [0x00, 0x41, 0x41, 0x7F, 0x00],  # ']'
    [0x04, 0x02, 0x01, 0x02, 0x04],  # '^'
    [0x40, 0x40, 0x40, 0x40, 0x40],  # '_'
    [0x00, 0x03, 0x05, 0x00, 0x00],  # '`'
    [0x20, 0x54, 0x54, 0x54, 0x78],  # 'a'
    [0x7F, 0x48, 0x44, 0x44, 0x38],  # 'b'
    [0x38, 0x44, 0x44, 0x44, 0x20],  # 'c'
    [0x38, 0x44, 0x44, 0x48, 0x7F],  # 'd'
    [0x38, 0x54, 0x54, 0x54, 0x18],  # 'e'
    [0x08, 0x7E, 0x09, 0x01, 0x02],  # 'f'
    [0x0C, 0x52, 0x52, 0x52, 0x3E],  # 'g'
    [0x7F, 0x08, 0x04, 0x04, 0x78],  # 'h'
    [0x00, 0x44, 0x7D, 0x40, 0x00],  # 'i'
    [0x20, 0x40, 0x44, 0x3D, 0x00],  # 'j'
    [0x7F, 0x10, 0x28, 0x44, 0x00],  # 'k'
    [0x00, 0x41, 0x7F, 0x40, 0x00],  # 'l'
    [0x7C, 0x04, 0x18, 0x04, 0x78],  # 'm'
    [0x7C, 0x08, 0x04, 0x04, 0x78],  # 'n'
    [0x38, 0x44, 0x44, 0x44, 0x38],  # 'o'
    [0x7C, 0x14, 0x14, 0x14, 0x08],  # 'p'
    [0x08, 0x14, 0x14, 0x14, 0x7C],  # 'q'
    [0x7C, 0x08, 0x04, 0x04, 0x08],  # 'r'
    [0x48, 0x54, 0x54, 0x54, 0x20],  # 's'
    [0x04, 0x3F, 0x44, 0x40, 0x20],  # 't'
    [0x3C, 0x40, 0x40, 0x20, 0x7C],  # 'u'
    [0x1C, 0x20, 0x40, 0x20, 0x1C],  # 'v'
    [0x3C, 0x40, 0x30, 0x40, 0x3C],  # 'w'
    [0x44, 0x28, 0x10, 0x28, 0x44],  # 'x'
    [0x0C, 0x50, 0x50, 0x50, 0x3C],  # 'y'
    [0x44, 0x64, 0x54, 0x4C, 0x44],  # 'z'
    [0x00, 0x08, 0x36, 0x41, 0x00],  # '{'
    [0x00, 0x00, 0x7F, 0x00, 0x00],  # '|'
    [0x00, 0x41, 0x36, 0x08, 0x00],  # '}'
    [0x10, 0x08, 0x08, 0x10, 0x08],  # '~'
]

# ============================================================================
# Farb-Konstanten
# ============================================================================

COLOR_WHITE = 0
COLOR_BLACK = 1
COLOR_YELLOW = 2
COLOR_RED = 3

# E-Paper-typische RGB-Farben
COLOR_MAP = {
    COLOR_WHITE:  (240, 240, 235),
    COLOR_BLACK:  (32, 32, 32),
    COLOR_YELLOW: (200, 184, 0),
    COLOR_RED:    (184, 0, 0),
}

# ============================================================================
# Display HAL Simulation
# ============================================================================

DISPLAY_WIDTH = 296
DISPLAY_HEIGHT = 128
FONT_W = 5
FONT_H = 7
CHAR_SPACING = 1
SCALE = 4  # Pixel-Skalierung für das Simulator-Fenster


class DisplayHAL:
    def __init__(self):
        self.framebuffer = [[COLOR_WHITE] * DISPLAY_WIDTH for _ in range(DISPLAY_HEIGHT)]

    def clear(self, color=COLOR_WHITE):
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                self.framebuffer[y][x] = color

    def _set_pixel(self, x, y, color):
        if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
            self.framebuffer[y][x] = color

    def draw_text(self, x, y, text, scale=1, color=COLOR_BLACK):
        cx = x
        for ch in text:
            if ch == '\n':
                cx = x
                y += FONT_H * scale + 2
                continue
            code = ord(ch)
            if code < 32 or code > 126:
                code = ord('?')
            glyph = FONT5X7[code - 32]
            for col in range(5):
                bits = glyph[col]
                for row in range(7):
                    if (bits >> row) & 0x01:
                        for sx in range(scale):
                            for sy in range(scale):
                                self._set_pixel(cx + col * scale + sx,
                                                y + row * scale + sy, color)
            cx += FONT_W * scale + CHAR_SPACING

    def draw_hline(self, x, y, w, color=COLOR_BLACK):
        for i in range(w):
            self._set_pixel(x + i, y, color)

    def draw_vline(self, x, y, h, color=COLOR_BLACK):
        for i in range(h):
            self._set_pixel(x, y + i, color)

    def draw_rect(self, x, y, w, h, color=COLOR_BLACK):
        for dy in range(h):
            for dx in range(w):
                self._set_pixel(x + dx, y + dy, color)

    def width(self):
        return DISPLAY_WIDTH

    def height(self):
        return DISPLAY_HEIGHT

    def render_to_photoimage(self, scale=SCALE):
        w, h = DISPLAY_WIDTH * scale, DISPLAY_HEIGHT * scale
        img = tk.PhotoImage(width=w, height=h)
        # Hex-Farben vorberechnen
        color_hex = {
            COLOR_WHITE:  "#F0F0EB",
            COLOR_BLACK:  "#202020",
            COLOR_YELLOW: "#C8B800",
            COLOR_RED:    "#B80000",
        }
        # Zeilen aufbauen und per put() setzen
        rows = []
        for y in range(DISPLAY_HEIGHT):
            row_colors = []
            for x in range(DISPLAY_WIDTH):
                hx = color_hex[self.framebuffer[y][x]]
                row_colors.extend([hx] * scale)
            row_str = " ".join(row_colors)
            for _ in range(scale):
                rows.append("{" + row_str + "}")
        img.put(" ".join(rows))
        return img


# ============================================================================
# UI Datenstruktur
# ============================================================================

class DisplayUIData:
    def __init__(self):
        self.temp_c = 22.5
        self.rh_pct = 55.0
        self.soil_pct = 62
        self.target_soil_pct = 60
        self.calib_raw_dry = 2600
        self.calib_raw_wet = 800
        self.soil_raw = self.pct_to_raw(self.soil_pct)
        self.last_measurement_unix = int(time_mod.time()) - 300
        self.next_measurement_unix = int(time_mod.time()) + 3300
        self.sleep_duration_s = 3300
        self.time_valid = True
        self.buffer_count = 0
        self.battery_voltage = 3.85
        self.ble_connected = True
        self.measurement_id = 42
        self.last_irrigation_ms = 0
        self.total_wakeups = 150
        self.avg_awake_s = 4.2
        self.ble_success_pct = 95.0

    def pct_to_raw(self, pct):
        """Berechnet Rohwert aus Prozent basierend auf Kalibrierung."""
        return int(self.calib_raw_dry - (pct / 100.0) * (self.calib_raw_dry - self.calib_raw_wet))

    def raw_to_pct(self, raw):
        """Berechnet Prozent aus Rohwert basierend auf Kalibrierung."""
        span = self.calib_raw_dry - self.calib_raw_wet
        if span == 0:
            return 0
        return max(0, min(100, int(round((self.calib_raw_dry - raw) / span * 100))))

    def set_soil_pct(self, pct):
        """Setzt Bodenfeuchte in % und aktualisiert Rohwert."""
        self.soil_pct = max(0, min(100, pct))
        self.soil_raw = self.pct_to_raw(self.soil_pct)

    def set_soil_raw(self, raw):
        """Setzt Sensor-Rohwert und aktualisiert Prozent."""
        self.soil_raw = raw
        self.soil_pct = self.raw_to_pct(raw)

    def set_calib(self, dry=None, wet=None):
        """Setzt Kalibrierungswerte und berechnet Prozent neu."""
        if dry is not None:
            self.calib_raw_dry = dry
        if wet is not None:
            self.calib_raw_wet = wet
        self.soil_pct = self.raw_to_pct(self.soil_raw)


# ============================================================================
# UI Rendering (1:1 Portierung aus display_ui.c)
# ============================================================================

DELTA_THRESHOLD_OK = 5
DELTA_THRESHOLD_WARN = 10


def _text_width(text, scale=1):
    return len(text) * (FONT_W * scale + CHAR_SPACING)


def _draw_text_right(hal, right_x, y, text, scale, color):
    tw = _text_width(text, scale)
    x = max(0, right_x - tw)
    hal.draw_text(x, y, text, scale, color)


# Zeitzone wie in der Firmware (config.h): MEZ plus Sommerzeit nach EU-Regel
TIMEZONE_OFFSET_S = 3600


def _is_eu_dst(unix_time):
    """EU-Sommerzeit: letzter Sonntag im März 01:00 UTC bis letzter Sonntag im Oktober 01:00 UTC."""
    t = datetime.fromtimestamp(unix_time, tz=timezone.utc)
    if t.month < 3 or t.month > 10:
        return False
    if 3 < t.month < 10:
        return True
    # März und Oktober haben 31 Tage; weekday(): Montag = 0, Sonntag = 6
    last_sunday = 31 - (datetime(t.year, t.month, 31).weekday() + 1) % 7
    if t.month == 3:
        return t.day > last_sunday or (t.day == last_sunday and t.hour >= 1)
    return t.day < last_sunday or (t.day == last_sunday and t.hour < 1)


def _local_offset(unix_time):
    return TIMEZONE_OFFSET_S + (3600 if _is_eu_dst(unix_time) else 0)


def _parse_local(text):
    """'HH:MM DD.MM.YYYY' in deutscher Zeit in Unix-Zeit umrechnen."""
    local = int(datetime.strptime(text, "%H:%M %d.%m.%Y").replace(tzinfo=timezone.utc).timestamp())
    return local - _local_offset(local - TIMEZONE_OFFSET_S)


def _format_datetime(unix_time):
    if unix_time == 0:
        return "--:-- --.--.----"
    # Lokalzeit wie auf dem echten Display
    dt = datetime.fromtimestamp(unix_time + _local_offset(unix_time), tz=timezone.utc)
    return dt.strftime("%H:%M %d.%m.%Y")


def _format_duration(seconds):
    if seconds < 90:
        return f"{seconds}sec"
    elif seconds < 3600:
        return f"{seconds // 60}min"
    else:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        if m > 0:
            return f"{h}h{m}min"
        return f"{h}h"


def _get_soil_color(current, target):
    abs_delta = abs(current - target)
    if abs_delta <= DELTA_THRESHOLD_OK:
        return COLOR_BLACK
    elif abs_delta <= DELTA_THRESHOLD_WARN:
        return COLOR_YELLOW
    return COLOR_RED


def show_normal_screen(hal, data):
    width = hal.width()
    margin = 4
    y = 4

    hal.clear(COLOR_WHITE)

    # Zeile 1: Temperatur links, Luftfeuchtigkeit rechts
    if math.isfinite(data.temp_c):
        buf = f"Temperatur: {data.temp_c:.1f}oC"
    else:
        buf = "Temperatur: --.-oC"
    hal.draw_text(margin, y, buf, 1, COLOR_BLACK)

    if math.isfinite(data.rh_pct):
        buf = f"Luftfeuchtigkeit: {round(data.rh_pct):.0f}%"
    else:
        buf = "Luftfeuchtigkeit: --%"
    _draw_text_right(hal, width - margin, y, buf, 1, COLOR_BLACK)

    y += 12
    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 4

    # Farbe für Bodenfeuchte
    soil_color = _get_soil_color(data.soil_pct, data.target_soil_pct)
    delta = data.soil_pct - data.target_soil_pct

    # Zeile 2: Bodenfeuchte groß und zentriert
    buf = f"BODEN: {data.soil_pct}%"
    tw = _text_width(buf, 2)
    center_x = (width - tw) // 2
    hal.draw_text(center_x, y, buf, 2, soil_color)
    y += FONT_H * 2 + 6

    # Zeile 3: Zielwert links, Delta rechts
    buf = f"Target: {data.target_soil_pct}%"
    hal.draw_text(margin, y, buf, 1, COLOR_BLACK)

    buf = f"Delta: {delta:+d}%"
    _draw_text_right(hal, width - margin, y, buf, 1, soil_color)
    y += 10

    # Fortschrittsbalken
    bar_x = margin
    bar_w = width - 2 * margin
    bar_h = 8

    hal.draw_hline(bar_x, y, bar_w, COLOR_BLACK)
    hal.draw_hline(bar_x, y + bar_h, bar_w, COLOR_BLACK)
    hal.draw_vline(bar_x, y, bar_h + 1, COLOR_BLACK)
    hal.draw_vline(bar_x + bar_w - 1, y, bar_h + 1, COLOR_BLACK)

    fill_w = ((bar_w - 4) * data.soil_pct) // 100
    fill_w = min(fill_w, bar_w - 4)
    if fill_w > 0:
        hal.draw_rect(bar_x + 2, y + 2, fill_w, bar_h - 3, soil_color)

    # Zielmarkierung (Dreieck)
    marker_x = bar_x + 2 + ((bar_w - 4) * data.target_soil_pct) // 100
    if bar_x <= marker_x < bar_x + bar_w:
        for i in range(3):
            hal.draw_hline(marker_x - i, y + bar_h + 2 + i, 2 * i + 1, COLOR_BLACK)

    y += bar_h + 8
    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 4

    # Zeile 4: Zeitstempel
    if data.time_valid:
        time_str = _format_datetime(data.last_measurement_unix)
        buf = f"Letzte Messung:   {time_str}"
        hal.draw_text(margin, y, buf, 1, COLOR_BLACK)
        y += 9

        time_str = _format_datetime(data.next_measurement_unix)
        buf = f"Naechste Messung: {time_str}"
        hal.draw_text(margin, y, buf, 1, COLOR_BLACK)

        if data.sleep_duration_s > 0:
            duration = _format_duration(data.sleep_duration_s)
            buf = f"(in {duration})"
            _draw_text_right(hal, width - margin, y, buf, 1, COLOR_BLACK)
        y += 10
    else:
        if data.sleep_duration_s > 0:
            duration = _format_duration(data.sleep_duration_s)
            buf = f"Naechste Messung in: {duration}"
            hal.draw_text(margin, y, buf, 1, COLOR_BLACK)
            y += 10
        hal.draw_text(margin, y, "Zeit: Nicht sync", 1, COLOR_BLACK)
        y += 10

    # Debug-Informationen
    buf = f"Sensor raw:{data.soil_raw}"
    hal.draw_text(margin, y, buf, 1, COLOR_BLACK)

    buf = f"Kalibration dry:{data.calib_raw_dry}  wet:{data.calib_raw_wet}"
    _draw_text_right(hal, width - margin, y, buf, 1, COLOR_BLACK)
    y += 9

    buf = f"Messungs ID:#{data.measurement_id}"
    hal.draw_text(margin, y, buf, 1, COLOR_BLACK)

    if data.last_irrigation_ms > 0:
        duration_s = data.last_irrigation_ms / 1000.0
        irr_buf = f"Gegossen: {duration_s:.1f}s"
    else:
        irr_buf = "Gegossen: 0s"
    _draw_text_right(hal, width - margin, y, irr_buf, 1, COLOR_BLACK)
    y += 9

    # Statistiken
    if math.isfinite(data.avg_awake_s) and data.avg_awake_s >= 0 and data.total_wakeups > 0:
        buf = f"Avg. Awake: {data.avg_awake_s:.1f}s | BLE Success: {data.ble_success_pct:.0f}%"
    else:
        buf = f"BLE Success: {data.ble_success_pct:.0f}%"
    hal.draw_text(margin, y, buf, 1, COLOR_BLACK)
    y += 9

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 4

    # Statuszeile
    char_w = FONT_W + CHAR_SPACING

    status_left = f"Buffer:{data.buffer_count}"
    if data.battery_voltage < 0.1:
        status_mid = "Bat:--V"
    else:
        status_mid = f"Bat:{data.battery_voltage:.1f}V"
    status_right = "[BT]" if data.ble_connected else "[ - ]"

    w_left = len(status_left) * char_w
    w_mid = len(status_mid) * char_w
    w_right = len(status_right) * char_w

    x_left = margin
    x_right = width - margin - w_right
    x_mid = (width - w_mid) // 2

    if x_mid < x_left + w_left + 1:
        x_mid = x_left + w_left + 1
    if x_mid + w_mid > x_right - 1:
        x_mid = x_right - 1 - w_mid

    buf_color = COLOR_RED if data.buffer_count > 0 else COLOR_BLACK
    ble_color = COLOR_BLACK if data.ble_connected else COLOR_RED

    hal.draw_text(x_left, y, status_left, 1, buf_color)
    hal.draw_text(x_mid, y, status_mid, 1, COLOR_BLACK)
    _draw_text_right(hal, width - margin, y, status_right, 1, ble_color)


# ============================================================================
# Weitere Screens (1:1 Portierung aus display_ui.c)
# ============================================================================

SCREEN_NORMAL = 0
SCREEN_SETUP = 1
SCREEN_CALIB_STEP1 = 2
SCREEN_CALIB_STEP2 = 3
SCREEN_CALIB_SUCCESS = 4
SCREEN_CALIB_TIMEOUT = 5
SCREEN_FACTORY_RESET_CONFIRM = 6
SCREEN_FACTORY_RESET_DONE = 7
SCREEN_CALIB_FAILED = 8

SCREEN_NAMES = {
    SCREEN_NORMAL: "Normal",
    SCREEN_SETUP: "Setup",
    SCREEN_CALIB_STEP1: "Kalibrierung 1/2",
    SCREEN_CALIB_STEP2: "Kalibrierung 2/2",
    SCREEN_CALIB_SUCCESS: "Kalibrierung OK",
    SCREEN_CALIB_TIMEOUT: "Kalibrierung Timeout",
    SCREEN_FACTORY_RESET_CONFIRM: "Werksreset Bestätigung",
    SCREEN_FACTORY_RESET_DONE: "Werksreset Fertig",
    SCREEN_CALIB_FAILED: "Kalibrierung ungültig",
}

NUM_SCREENS = 9


def show_setup_screen(hal):
    width = hal.width()
    height = hal.height()
    margin = 6

    hal.clear(COLOR_WHITE)

    title = "ElHydro"
    title_w = _text_width(title, 1)
    title_x = (width - title_w) // 2
    title_y = 10

    hal.draw_text(title_x, title_y, title, 1, COLOR_BLACK)
    hal.draw_hline(margin, title_y + FONT_H + 3, width - 2 * margin, COLOR_BLACK)

    card_x = margin
    card_y = 28
    card_w = width - 2 * margin
    card_h = height - card_y - margin

    hal.draw_hline(card_x, card_y, card_w, COLOR_BLACK)
    hal.draw_hline(card_x, card_y + card_h - 1, card_w, COLOR_BLACK)
    hal.draw_vline(card_x, card_y, card_h, COLOR_BLACK)
    hal.draw_vline(card_x + card_w - 1, card_y, card_h, COLOR_BLACK)

    msg = "Verbinde per Bluetooth"
    msg_w = _text_width(msg, 2)
    msg_h = FONT_H * 2
    msg_x = card_x + (card_w - msg_w) // 2
    msg_y = card_y + (card_h - msg_h) // 2 - 6

    hal.draw_text(msg_x, msg_y, msg, 2, COLOR_RED)

    footer = "Noch nicht eingerichtet"
    footer_w = _text_width(footer, 1)
    footer_x = card_x + (card_w - footer_w) // 2
    footer_y = card_y + card_h - 14

    hal.draw_text(footer_x, footer_y, footer, 1, COLOR_RED)


def show_calibration_step1(hal):
    width = hal.width()
    margin = 6
    y = 10

    hal.clear(COLOR_WHITE)

    title = "KALIBRIERUNG"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 8

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 6

    hal.draw_text(margin, y, "Schritt 1/2:", 2, COLOR_BLACK)
    y += FONT_H * 2 + 6

    hal.draw_text(margin, y, "1. Sensor abtrocknen", 1, COLOR_BLACK)
    y += FONT_H + 4

    hal.draw_text(margin, y, "2. In Luft halten", 1, COLOR_BLACK)
    y += FONT_H + 8

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 6

    hal.draw_text(margin, y, "Boot-Taste", 2, COLOR_BLACK)
    y += FONT_H * 2 + 2

    hal.draw_text(margin, y, "druecken wenn bereit", 2, COLOR_BLACK)


def show_calibration_step2(hal):
    width = hal.width()
    margin = 6
    y = 10

    hal.clear(COLOR_WHITE)

    title = "KALIBRIERUNG"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 8

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 6

    hal.draw_text(margin, y, "Schritt 2/2:", 2, COLOR_BLACK)
    y += FONT_H * 2 + 6

    hal.draw_text(margin, y, "Sensor komplett", 1, COLOR_BLACK)
    y += FONT_H + 4

    hal.draw_text(margin, y, "in Wasser tauchen", 1, COLOR_BLACK)
    y += FONT_H + 8

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 6

    hal.draw_text(margin, y, "Boot-Taste", 2, COLOR_BLACK)
    y += FONT_H * 2 + 2

    hal.draw_text(margin, y, "druecken wenn bereit", 2, COLOR_BLACK)


def show_calibration_success(hal, raw_dry=2600, raw_wet=800):
    width = hal.width()
    margin = 6
    y = 6

    hal.clear(COLOR_WHITE)

    title = "KALIBRIERUNG"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 4

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 3

    success = "ERFOLGREICH!"
    success_w = _text_width(success, 2)
    hal.draw_text((width - success_w) // 2, y, success, 2, COLOR_BLACK)
    y += FONT_H * 2 + 6

    buf = f"Trocken: {raw_dry}"
    hal.draw_text(margin, y, buf, 2, COLOR_BLACK)
    y += FONT_H * 2 + 3

    buf = f"Nass:    {raw_wet}"
    hal.draw_text(margin, y, buf, 2, COLOR_BLACK)
    y += FONT_H * 2 + 6

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 3

    hal.draw_text(margin, y, "Werte gespeichert", 1, COLOR_BLACK)
    y += FONT_H + 3

    hal.draw_text(margin, y, "Boot-Taste", 2, COLOR_BLACK)
    y += FONT_H * 2 + 2

    hal.draw_text(margin, y, "druecken zum Starten", 2, COLOR_BLACK)


def show_calibration_timeout(hal):
    width = hal.width()
    margin = 6
    y = 20

    hal.clear(COLOR_WHITE)

    title = "KALIBRIERUNG"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 8

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 10

    timeout_msg = "TIMEOUT"
    timeout_w = _text_width(timeout_msg, 2)
    hal.draw_text((width - timeout_w) // 2, y, timeout_msg, 2, COLOR_RED)
    y += FONT_H * 2 + 10

    hal.draw_text(margin, y, "Kalibrierung", 1, COLOR_BLACK)
    y += FONT_H + 4

    hal.draw_text(margin, y, "uebersprungen", 1, COLOR_BLACK)
    y += FONT_H + 10

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 6

    hal.draw_text(margin, y, "Alte Werte behalten", 1, COLOR_BLACK)


def show_calibration_failed(hal, raw_dry=800, raw_wet=2600):
    width = hal.width()
    margin = 6
    y = 6

    hal.clear(COLOR_WHITE)

    title = "KALIBRIERUNG"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 4

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 3

    failed = "UNGUELTIG"
    failed_w = _text_width(failed, 2)
    hal.draw_text((width - failed_w) // 2, y, failed, 2, COLOR_RED)
    y += FONT_H * 2 + 6

    hal.draw_text(margin, y, f"Trocken: {raw_dry}  Nass: {raw_wet}", 1, COLOR_BLACK)
    y += FONT_H + 4

    hal.draw_text(margin, y, "Trocken muss deutlich ueber Nass liegen.", 1, COLOR_BLACK)
    y += FONT_H + 2

    hal.draw_text(margin, y, "Alte Werte behalten.", 1, COLOR_BLACK)
    y += FONT_H + 6

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 3

    hal.draw_text(margin, y, "Boot-Taste", 2, COLOR_BLACK)
    y += FONT_H * 2 + 2

    hal.draw_text(margin, y, "druecken zum Starten", 2, COLOR_BLACK)


def show_factory_reset_confirm(hal):
    width = hal.width()
    margin = 6
    y = 4

    hal.clear(COLOR_WHITE)

    title = "WERKSRESET"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 4

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 4

    hal.draw_text(margin, y, "Reset ausloesen?", 1, COLOR_RED)
    y += FONT_H + 4

    hal.draw_text(margin, y, "5x Reset-Taste gedrueckt.", 1, COLOR_BLACK)
    y += FONT_H + 2

    hal.draw_text(margin, y, "Alle Einstellungen und", 1, COLOR_BLACK)
    y += FONT_H + 2

    hal.draw_text(margin, y, "Messwerte werden geloescht.", 1, COLOR_BLACK)
    y += FONT_H + 4

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 6

    hal.draw_text(margin, y, "Boot-Taste = JA", 2, COLOR_BLACK)
    y += FONT_H * 2 + 4

    hal.draw_text(margin, y, "Warten = Abbrechen", 2, COLOR_BLACK)


def show_factory_reset_done(hal):
    width = hal.width()
    margin = 6
    y = 20

    hal.clear(COLOR_WHITE)

    title = "WERKSRESET"
    title_w = _text_width(title, 2)
    hal.draw_text((width - title_w) // 2, y, title, 2, COLOR_BLACK)
    y += FONT_H * 2 + 10

    hal.draw_hline(margin, y, width - 2 * margin, COLOR_BLACK)
    y += 10

    msg1 = "WERKSEINSTELLUNGEN"
    msg1_w = _text_width(msg1, 1)
    hal.draw_text((width - msg1_w) // 2, y, msg1, 1, COLOR_BLACK)
    y += FONT_H + 4

    msg2 = "WURDEN WIEDERHERGESTELLT"
    msg2_w = _text_width(msg2, 1)
    hal.draw_text((width - msg2_w) // 2, y, msg2, 1, COLOR_BLACK)
    y += FONT_H + 10

    hal.draw_text(margin, y, "Bitte erneut per PC", 1, COLOR_BLACK)
    y += FONT_H + 2

    hal.draw_text(margin, y, "einrichten.", 1, COLOR_BLACK)


def render_screen(hal, screen_id, data):
    if screen_id == SCREEN_NORMAL:
        show_normal_screen(hal, data)
    elif screen_id == SCREEN_SETUP:
        show_setup_screen(hal)
    elif screen_id == SCREEN_CALIB_STEP1:
        show_calibration_step1(hal)
    elif screen_id == SCREEN_CALIB_STEP2:
        show_calibration_step2(hal)
    elif screen_id == SCREEN_CALIB_SUCCESS:
        show_calibration_success(hal, data.calib_raw_dry, data.calib_raw_wet)
    elif screen_id == SCREEN_CALIB_TIMEOUT:
        show_calibration_timeout(hal)
    elif screen_id == SCREEN_FACTORY_RESET_CONFIRM:
        show_factory_reset_confirm(hal)
    elif screen_id == SCREEN_FACTORY_RESET_DONE:
        show_factory_reset_done(hal)
    elif screen_id == SCREEN_CALIB_FAILED:
        # Vertauschte Schritte: Trockenwert unter dem Nasswert
        show_calibration_failed(hal, data.calib_raw_wet, data.calib_raw_dry)


# ============================================================================
# Terminal-Eingabe
# ============================================================================

HELP_TEXT = """
=== elHydro E-Paper Simulator ===

Fenster:
  Pfeiltasten Links/Rechts   Screen wechseln
  Pfeiltasten Hoch/Runter    Bodenfeuchte +/- 5%
  ESC                        Beenden

Terminal-Befehle (Eingabe + Enter):
  screen <0-8>               Screen wechseln
  temp <wert>                Temperatur in °C          (z.B. temp 22.5)
  rh <wert>                  Luftfeuchtigkeit in %     (z.B. rh 55)
  soil <wert>                Bodenfeuchte in %         (z.B. soil 62)
  target <wert>              Ziel-Bodenfeuchte in %    (z.B. target 60)
  raw <wert>                 Sensor-Rohwert            (z.B. raw 1450)
  dry <wert>                 Kalibrierung trocken      (z.B. dry 2600)
  wet <wert>                 Kalibrierung nass         (z.B. wet 800)
  bat <wert>                 Batteriespannung in V     (z.B. bat 3.85)
  buffer <wert>              Buffer-Anzahl             (z.B. buffer 2)
  ble <on|off>               BLE verbunden/getrennt    (z.B. ble off)
  time <on|off>              Zeitsync an/aus           (z.B. time off)
  sleep <sekunden>           Schlafdauer               (z.B. sleep 3600)
  last <HH:MM DD.MM.YYYY>   Letzte Messung             (z.B. last 14:30 01.04.2026)
  next <HH:MM DD.MM.YYYY>   Nächste Messung            (z.B. next 15:30 01.04.2026)
  irrigation <ms>            Letzte Bewässerung in ms  (z.B. irrigation 2500)
  id <wert>                  Messungs-ID               (z.B. id 42)
  wakeups <wert>             Gesamte Wakeups           (z.B. wakeups 150)
  awake <wert>               Avg. Awake in Sekunden    (z.B. awake 4.2)
  blesuccess <wert>          BLE Erfolgsrate in %      (z.B. blesuccess 95)
  random                     Zufällige Werte
  values                     Alle aktuellen Werte anzeigen
  help                       Diese Hilfe anzeigen
  quit                       Beenden
"""


def print_values(data, current_screen):
    print(f"\n  --- Aktuelle Werte (Screen: {SCREEN_NAMES[current_screen]}) ---")
    print(f"  temp={data.temp_c:.1f}°C  rh={data.rh_pct:.0f}%  "
          f"soil={data.soil_pct}%  target={data.target_soil_pct}%")
    print(f"  raw={data.soil_raw}  dry={data.calib_raw_dry}  wet={data.calib_raw_wet}")
    print(f"  bat={data.battery_voltage:.2f}V  buffer={data.buffer_count}  "
          f"ble={'on' if data.ble_connected else 'off'}  "
          f"time={'on' if data.time_valid else 'off'}")
    print(f"  sleep={data.sleep_duration_s}s  irrigation={data.last_irrigation_ms}ms  "
          f"id={data.measurement_id}")
    print(f"  wakeups={data.total_wakeups}  awake={data.avg_awake_s:.1f}s  "
          f"blesuccess={data.ble_success_pct:.0f}%")
    print()


def parse_command(line, data, state):
    """Parst einen Terminal-Befehl. Gibt True zurück wenn Redraw nötig."""
    parts = line.strip().split(None, 1)
    if not parts:
        return False

    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    try:
        if cmd == "help":
            print(HELP_TEXT)
            return False
        elif cmd == "quit" or cmd == "exit":
            state["running"] = False
            return False
        elif cmd == "values":
            print_values(data, state["screen"])
            return False
        elif cmd == "screen":
            n = int(arg)
            if 0 <= n < NUM_SCREENS:
                state["screen"] = n
                print(f"  Screen: {SCREEN_NAMES[n]}")
                return True
            print(f"  Fehler: Screen muss 0-{NUM_SCREENS - 1} sein")
        elif cmd == "temp":
            data.temp_c = float(arg)
            print(f"  Temperatur: {data.temp_c:.1f}°C")
            return True
        elif cmd == "rh":
            data.rh_pct = max(0, min(100, float(arg)))
            print(f"  Luftfeuchtigkeit: {data.rh_pct:.0f}%")
            return True
        elif cmd == "soil":
            data.set_soil_pct(int(arg))
            print(f"  Bodenfeuchte: {data.soil_pct}%  (raw: {data.soil_raw})")
            return True
        elif cmd == "target":
            data.target_soil_pct = max(0, min(100, int(arg)))
            print(f"  Ziel-Bodenfeuchte: {data.target_soil_pct}%")
            return True
        elif cmd == "raw":
            data.set_soil_raw(int(arg))
            print(f"  Sensor raw: {data.soil_raw}  (soil: {data.soil_pct}%)")
            return True
        elif cmd == "dry":
            data.set_calib(dry=int(arg))
            print(f"  Kalibrierung trocken: {data.calib_raw_dry}  (soil: {data.soil_pct}%)")
            return True
        elif cmd == "wet":
            data.set_calib(wet=int(arg))
            print(f"  Kalibrierung nass: {data.calib_raw_wet}  (soil: {data.soil_pct}%)")
            return True
        elif cmd == "bat":
            data.battery_voltage = float(arg)
            print(f"  Batterie: {data.battery_voltage:.2f}V")
            return True
        elif cmd == "buffer":
            data.buffer_count = max(0, int(arg))
            print(f"  Buffer: {data.buffer_count}")
            return True
        elif cmd == "ble":
            data.ble_connected = arg.lower() in ("on", "1", "true", "ja")
            print(f"  BLE: {'verbunden' if data.ble_connected else 'getrennt'}")
            return True
        elif cmd == "time":
            data.time_valid = arg.lower() in ("on", "1", "true", "ja")
            print(f"  Zeitsync: {'an' if data.time_valid else 'aus'}")
            return True
        elif cmd == "sleep":
            data.sleep_duration_s = max(0, int(arg))
            now = int(time_mod.time())
            data.next_measurement_unix = now + data.sleep_duration_s
            data.last_measurement_unix = now
            print(f"  Schlafdauer: {data.sleep_duration_s}s")
            return True
        elif cmd == "last":
            data.last_measurement_unix = _parse_local(arg)
            print(f"  Letzte Messung: {_format_datetime(data.last_measurement_unix)}")
            return True
        elif cmd == "next":
            data.next_measurement_unix = _parse_local(arg)
            data.sleep_duration_s = max(0, data.next_measurement_unix - int(time_mod.time()))
            print(f"  Nächste Messung: {_format_datetime(data.next_measurement_unix)}")
            return True
        elif cmd == "irrigation":
            data.last_irrigation_ms = max(0, int(arg))
            print(f"  Bewässerung: {data.last_irrigation_ms}ms")
            return True
        elif cmd == "id":
            data.measurement_id = int(arg)
            print(f"  Messungs-ID: {data.measurement_id}")
            return True
        elif cmd == "wakeups":
            data.total_wakeups = max(0, int(arg))
            print(f"  Wakeups: {data.total_wakeups}")
            return True
        elif cmd == "awake":
            data.avg_awake_s = float(arg)
            print(f"  Avg. Awake: {data.avg_awake_s:.1f}s")
            return True
        elif cmd == "blesuccess":
            data.ble_success_pct = max(0, min(100, float(arg)))
            print(f"  BLE Success: {data.ble_success_pct:.0f}%")
            return True
        elif cmd == "random":
            import random
            data.temp_c = round(random.uniform(15, 35), 1)
            data.rh_pct = round(random.uniform(30, 90))
            data.set_soil_pct(random.randint(10, 95))
            data.target_soil_pct = random.randint(40, 80)
            data.buffer_count = random.choice([0, 0, 0, 1, 3])
            data.battery_voltage = round(random.uniform(3.0, 4.2), 2)
            data.ble_connected = random.choice([True, True, False])
            data.last_irrigation_ms = random.choice([0, 0, 0, 2500, 5000])
            data.measurement_id = random.randint(1, 99999)
            now = int(time_mod.time())
            data.last_measurement_unix = now - random.randint(60, 7200)
            data.sleep_duration_s = random.choice([300, 900, 1800, 3600])
            data.next_measurement_unix = now + data.sleep_duration_s
            print_values(data, state["screen"])
            return True
        else:
            print(f"  Unbekannter Befehl: {cmd} (Tippe 'help' für Hilfe)")
    except (ValueError, IndexError):
        print(f"  Fehler: Ungültiger Wert für '{cmd}'")
    return False


# ============================================================================
# Hauptprogramm
# ============================================================================

def main():
    import threading
    import queue

    print(HELP_TEXT)

    hal = DisplayHAL()
    data = DisplayUIData()
    state = {"screen": SCREEN_NORMAL, "running": True}

    # tkinter Fenster
    root = tk.Tk()
    root.title("elHydro E-Paper Simulator (296x128)")
    root.resizable(False, False)

    win_w = DISPLAY_WIDTH * SCALE
    win_h = DISPLAY_HEIGHT * SCALE
    canvas = tk.Canvas(root, width=win_w, height=win_h, highlightthickness=0)
    canvas.pack()

    # Bild-Referenz (muss gehalten werden damit GC es nicht freigibt)
    img_ref = [None]

    def redraw():
        render_screen(hal, state["screen"], data)
        img_ref[0] = hal.render_to_photoimage(SCALE)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor=tk.NW, image=img_ref[0])

    # Tastatur-Events
    def on_key(event):
        if event.keysym == "Escape":
            state["running"] = False
            root.destroy()
        elif event.keysym == "Left":
            state["screen"] = (state["screen"] - 1) % NUM_SCREENS
            print(f"  Screen: {SCREEN_NAMES[state['screen']]}")
            redraw()
        elif event.keysym == "Right":
            state["screen"] = (state["screen"] + 1) % NUM_SCREENS
            print(f"  Screen: {SCREEN_NAMES[state['screen']]}")
            redraw()
        elif event.keysym == "Up":
            data.set_soil_pct(data.soil_pct + 5)
            redraw()
        elif event.keysym == "Down":
            data.set_soil_pct(data.soil_pct - 5)
            redraw()

    root.bind("<Key>", on_key)

    # Terminal-Eingabe in eigenem Thread
    cmd_queue = queue.Queue()

    def input_thread():
        while state["running"]:
            try:
                line = input("epaper> ")
                cmd_queue.put(line)
            except EOFError:
                break

    t = threading.Thread(target=input_thread, daemon=True)
    t.start()

    # Terminal-Befehle per Polling verarbeiten
    def poll_commands():
        if not state["running"]:
            return
        changed = False
        while not cmd_queue.empty():
            line = cmd_queue.get_nowait()
            if parse_command(line, data, state):
                changed = True
        if changed:
            redraw()
        if not state["running"]:
            root.destroy()
            return
        root.after(50, poll_commands)

    def on_close():
        state["running"] = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # Erster Draw + Polling starten
    redraw()
    root.after(50, poll_commands)
    root.mainloop()


def start_embedded(parent):
    """Startet den Simulator als Toplevel-Fenster (für Integration in Launcher/.exe).
    Ersetzt Terminal-Ein/Ausgabe durch tkinter-Widgets."""
    import io
    import sys as _sys

    hal = DisplayHAL()
    data = DisplayUIData()
    state = {"screen": SCREEN_NORMAL, "running": True}

    top = tk.Toplevel(parent)
    top.title("elHydro E-Paper Simulator (296x128)")
    top.resizable(False, False)

    # Display-Canvas
    canvas = tk.Canvas(top, width=DISPLAY_WIDTH * SCALE,
                       height=DISPLAY_HEIGHT * SCALE, highlightthickness=0)
    canvas.pack()

    # Screen-Info
    screen_label = tk.Label(top, text=f"Screen: {SCREEN_NAMES[SCREEN_NORMAL]}",
                            anchor="w", font=("Consolas", 9))
    screen_label.pack(fill="x", padx=4, pady=(4, 0))

    # Ausgabe-Textfeld (ersetzt Terminal-Output)
    output = tk.Text(top, height=12, state="disabled",
                     font=("Consolas", 9), wrap="word")
    output.pack(fill="x", padx=4, pady=(2, 0))

    # Eingabezeile (ersetzt Terminal-Input)
    frame_cmd = tk.Frame(top)
    frame_cmd.pack(fill="x", padx=4, pady=4)
    tk.Label(frame_cmd, text="epaper>", font=("Consolas", 9)).pack(side="left")
    entry = tk.Entry(frame_cmd, font=("Consolas", 11))
    entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
    entry.focus_set()

    img_ref = [None]

    def log_output(text):
        output.config(state="normal")
        output.insert("end", text + "\n")
        output.see("end")
        output.config(state="disabled")

    def redraw():
        render_screen(hal, state["screen"], data)
        img_ref[0] = hal.render_to_photoimage(SCALE)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor=tk.NW, image=img_ref[0])
        screen_label.config(text=f"Screen: {SCREEN_NAMES[state['screen']]}")

    def on_command(event=None):
        line = entry.get().strip()
        entry.delete(0, "end")
        if not line:
            return
        # print()-Ausgaben von parse_command abfangen
        buf = io.StringIO()
        old_stdout = _sys.stdout
        _sys.stdout = buf
        try:
            changed = parse_command(line, data, state)
        finally:
            _sys.stdout = old_stdout
        captured = buf.getvalue().strip()
        if captured:
            log_output(captured)
        if changed:
            redraw()
        if not state["running"]:
            top.destroy()

    entry.bind("<Return>", on_command)

    def on_key(event):
        if event.widget == entry:
            return
        if event.keysym == "Escape":
            top.destroy()
        elif event.keysym == "Left":
            state["screen"] = (state["screen"] - 1) % NUM_SCREENS
            log_output(f"Screen: {SCREEN_NAMES[state['screen']]}")
            redraw()
        elif event.keysym == "Right":
            state["screen"] = (state["screen"] + 1) % NUM_SCREENS
            log_output(f"Screen: {SCREEN_NAMES[state['screen']]}")
            redraw()
        elif event.keysym == "Up":
            data.set_soil_pct(data.soil_pct + 5)
            redraw()
        elif event.keysym == "Down":
            data.set_soil_pct(data.soil_pct - 5)
            redraw()

    top.bind("<Key>", on_key)

    log_output("E-Paper Simulator gestartet. 'help' für Hilfe.")
    redraw()


if __name__ == "__main__":
    main()
