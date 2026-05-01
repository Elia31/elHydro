#pragma once
#include <stdint.h>
// Quelle: https://lexus2k.github.io/ssd1306/ssd1306__fonts_8c_source.html
// 5x7 Font (ASCII 0x20..0x7E), jede Glyphe = 5 Spalten à 8 Bits
// -> Darstellung von links nach rechts, LSB = oberstes Pixel
extern const uint8_t font5x7[95][5];
