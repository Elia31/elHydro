/**
 * @file pins.h
 * @brief Hardware-Zuordnung für elHydro (ESP32-C6)
 *
 * Enthält ALLE physischen GPIO- und Peripherie-Zuordnungen.
 * Jede Änderung an der Hardware (andere Pins, Sensoren, Displaytyp)
 * wird ausschließlich hier vorgenommen.
 */

#ifndef PINS_H
#define PINS_H

#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_adc/adc_oneshot.h"

// ============================================================================
// I2C-Bus (HTU21D Temperatur-/Feuchtigkeitssensor)
// ============================================================================

#define I2C_PORT       I2C_NUM_0
#define I2C_SDA_GPIO   22
#define I2C_SCL_GPIO   21
#define I2C_CLK_HZ     100000 // 100 kHz
#define I2C_TIMEOUT_MS 1000
#define I2C_PULLUPS    true // Interne Pull-Ups aktivieren

// ============================================================================
// SPI-Bus (2.9" E-Paper Display)
// ============================================================================

#define PIN_MOSI 19 // SDI
#define PIN_SCLK 5
#define PIN_CS   4
#define PIN_DC   3 // D/C
#define PIN_RST  15
#define PIN_BUSY 6
#define SPI_HZ   (4 * 1000 * 1000) // 4 MHz

// ============================================================================
// Bodenfeuchtesensor (LM393 / kapazitiv v2.0, geteilter ADC)
// ============================================================================

#define SOIL_ADC_UNIT    ADC_UNIT_1
#define SOIL_ADC_CHANNEL ADC_CHANNEL_1 // GPIO1
#define SOIL_DO_GPIO     GPIO_NUM_NC   // Digitaler Schwellwert-Ausgang (aktuell nicht verdrahtet)
#define SOIL_SAMPLES     8             // Anzahl Messungen für Mittelwert

// ============================================================================
// Taster
// ============================================================================

#define BTN_GPIO    GPIO_NUM_9 // Boot-Taste (Active Low)
#define BTN_LONG_MS 2000       // Long-Press Schwelle

// ============================================================================
// Wasserpumpe (JT-DC3W, MOSFET-gesteuert)
// ============================================================================

#define PUMP_GPIO         GPIO_NUM_8 // MOSFET Gate (10kΩ Pull-Down)
#define PUMP_ACTIVE_LEVEL 1          // HIGH = an, LOW = aus

// ============================================================================
// Stromversorgung (schaltbare VCC-Pins für Sensoren)
// ============================================================================

#define TEMP_SENSOR_VCC_PIN GPIO_NUM_23 // HTU21D Versorgung
#define SOIL_VCC_PIN        GPIO_NUM_18 // Bodenfeuchtesensor Versorgung
#define DISPLAY_VCC_PIN     GPIO_NUM_20 // E-Paper Versorgung

// ============================================================================
// Batteriemessung (FireBeetle 2 integrierter Spannungsteiler auf GPIO0)
// ============================================================================

#define ENABLE_BATTERY_ADC 1 // 1 = aktivieren, 0 = deaktivieren

#define VBAT_ADC_UNIT     ADC_UNIT_1
#define VBAT_ADC_CHANNEL  ADC_CHANNEL_0 // GPIO0
#define VBAT_SCALE_FACTOR 2.0f          // Spannungsteiler-Faktor (1:1 Teiler)
#define VBAT_OFFSET_MV    0.0f          // Kein Offset
#define ADC_MAX_CODE      4095.0f       // 12-Bit ADC Auflösung

#endif // PINS_H
