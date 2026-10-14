/**
 * @file epd_bw_driver.c
 * @brief Treiber für 2.9" E-Paper Display (Schwarz/Weiß)
 *
 * https://www.good-display.com/product/389.html
 * https://www.good-display.com/companyfile/1116.html
 */

#include "epd_bw_driver.h"

#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char* TAG = "EPD_BW";

// ============================================================================
// Konstanten
// ============================================================================

// Framebuffer-Größe (1 Bit pro Pixel)
#define FRAMEBUFFER_SIZE ((EPD_PHYS_WIDTH * EPD_PHYS_HEIGHT) / 8)

// Timeout für BUSY-Pin
#define BUSY_TIMEOUT_US 5000000 // 5 Sekunden

// ============================================================================
// SPI-Kommunikation
// ============================================================================

static esp_err_t send_command(epd_bw_t* epd, uint8_t cmd)
{
    gpio_set_level(epd->pin_dc, 0);
    spi_transaction_t t = { .length = 8, .tx_buffer = &cmd };
    return spi_device_transmit(epd->spi, &t);
}

static esp_err_t send_data(epd_bw_t* epd, const void* data, size_t len)
{
    gpio_set_level(epd->pin_dc, 1);
    spi_transaction_t t = { .length = len * 8, .tx_buffer = data };
    return spi_device_transmit(epd->spi, &t);
}

static esp_err_t send_data_byte(epd_bw_t* epd, uint8_t value)
{
    return send_data(epd, &value, 1);
}

// ============================================================================
// BUSY-Pin Handling
// ============================================================================

static esp_err_t wait_busy(epd_bw_t* epd, const char* context)
{
    if (epd->debug)
    {
        ESP_LOGI(TAG, "Warte auf BUSY: %s", context);
    }

    int64_t start = esp_timer_get_time();

    while (gpio_get_level(epd->pin_busy) != 0)
    {
        vTaskDelay(pdMS_TO_TICKS(5));

        if (esp_timer_get_time() - start > BUSY_TIMEOUT_US)
        {
            ESP_LOGW(TAG, "BUSY Timeout bei: %s", context);
            return ESP_ERR_TIMEOUT;
        }
    }
    return ESP_OK;
}

// ============================================================================
// Koordinatentransformation (logisch → physisch)
// ============================================================================

static void transform_coords(epd_bw_t* epd, int x, int y, int* phys_x, int* phys_y)
{
    if (epd->upside_down)
    {
        // Querformat gedreht (ehem. ROT_270)
        *phys_x = EPD_PHYS_WIDTH - 1 - y;
        *phys_y = x;
    }
    else
    {
        // Querformat normal (ehem. ROT_90)
        *phys_x = y;
        *phys_y = EPD_PHYS_HEIGHT - 1 - x;
    }
}

// ============================================================================
// Reset-Funktionen
// ============================================================================

static esp_err_t hardware_reset(epd_bw_t* epd)
{
    gpio_set_level(epd->pin_rst, 0);
    vTaskDelay(pdMS_TO_TICKS(10));
    gpio_set_level(epd->pin_rst, 1);
    vTaskDelay(pdMS_TO_TICKS(10));
    return wait_busy(epd, "Hardware-Reset");
}

static esp_err_t software_reset(epd_bw_t* epd)
{
    send_command(epd, 0x12);
    return wait_busy(epd, "Software-Reset");
}

// ============================================================================
// SSD1680 Initialisierungssequenz
// ============================================================================

static esp_err_t init_sequence(epd_bw_t* epd)
{
    if (hardware_reset(epd) != ESP_OK || software_reset(epd) != ESP_OK)
    {
        return ESP_ERR_TIMEOUT;
    }

    // Driver Output Control (128x296)
    send_command(epd, 0x01);
    send_data_byte(epd, (EPD_PHYS_HEIGHT - 1) & 0xFF);
    send_data_byte(epd, ((EPD_PHYS_HEIGHT - 1) >> 8) & 0xFF);
    send_data_byte(epd, 0x00);

    // Data Entry Mode: X+, Y+
    send_command(epd, 0x11);
    send_data_byte(epd, 0x03);

    // RAM X-Adressbereich (0 bis 15, da 128/8=16)
    send_command(epd, 0x44);
    send_data_byte(epd, 0x00);
    send_data_byte(epd, (EPD_PHYS_WIDTH / 8) - 1);

    // RAM Y-Adressbereich (0 bis 295)
    send_command(epd, 0x45);
    send_data_byte(epd, 0x00);
    send_data_byte(epd, 0x00);
    send_data_byte(epd, (EPD_PHYS_HEIGHT - 1) & 0xFF);
    send_data_byte(epd, ((EPD_PHYS_HEIGHT - 1) >> 8) & 0xFF);

    // Border Waveform
    send_command(epd, 0x3C);
    send_data_byte(epd, 0x05);

    // Display Update Control
    send_command(epd, 0x21);
    send_data_byte(epd, 0x00);
    send_data_byte(epd, 0x80);

    // Temperatursensor (intern)
    send_command(epd, 0x18);
    send_data_byte(epd, 0x80);

    // RAM X-Pointer
    send_command(epd, 0x4E);
    send_data_byte(epd, 0x00);

    // RAM Y-Pointer
    send_command(epd, 0x4F);
    send_data_byte(epd, 0x00);
    send_data_byte(epd, 0x00);

    return wait_busy(epd, "Init-Sequenz");
}

// ============================================================================
// Öffentliche API
// ============================================================================

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
                      bool              debug)
{
    if (!epd)
    {
        return ESP_ERR_INVALID_ARG;
    }

    memset(epd, 0, sizeof(*epd));

    epd->pin_dc      = dc;
    epd->pin_rst     = rst;
    epd->pin_busy    = busy;
    epd->debug       = debug;
    epd->upside_down = upside_down;

    // Immer Querformat
    epd->width  = EPD_PHYS_HEIGHT;
    epd->height = EPD_PHYS_WIDTH;

    ESP_LOGI(TAG,
             "Init: UpsideDown=%s, logisch=%dx%d, physisch=%dx%d",
             upside_down ? "ja" : "nein",
             epd->width,
             epd->height,
             EPD_PHYS_WIDTH,
             EPD_PHYS_HEIGHT);

    // GPIO konfigurieren
    gpio_config_t io_conf = { .pin_bit_mask = (1ULL << dc) | (1ULL << rst),
                              .mode         = GPIO_MODE_OUTPUT,
                              .pull_up_en   = GPIO_PULLUP_DISABLE,
                              .pull_down_en = GPIO_PULLDOWN_DISABLE,
                              .intr_type    = GPIO_INTR_DISABLE };

    esp_err_t ret = gpio_config(&io_conf);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "GPIO-Konfiguration fehlgeschlagen");
        return ret;
    }

    gpio_set_direction(busy, GPIO_MODE_INPUT);
    gpio_set_level(rst, 1);

    // SPI-Bus initialisieren
    spi_bus_config_t bus_cfg = { .mosi_io_num = mosi, .miso_io_num = -1, .sclk_io_num = sclk, .max_transfer_sz = 4096 };

    ret = spi_bus_initialize(host, &bus_cfg, SPI_DMA_CH_AUTO);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "SPI-Bus Initialisierung fehlgeschlagen");
        return ret;
    }

    spi_device_interface_config_t dev_cfg = { .clock_speed_hz = spi_hz, .mode = 0, .spics_io_num = cs, .queue_size = 7 };

    ret = spi_bus_add_device(host, &dev_cfg, &epd->spi);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "SPI-Device Hinzufügen fehlgeschlagen");
        spi_bus_free(host);
        return ret;
    }

    // Framebuffer allokieren
    epd->framebuffer = (uint8_t*) heap_caps_malloc(FRAMEBUFFER_SIZE, MALLOC_CAP_8BIT);
    if (!epd->framebuffer)
    {
        ESP_LOGE(TAG, "Framebuffer-Allokation fehlgeschlagen");
        spi_bus_remove_device(epd->spi);
        spi_bus_free(host);
        return ESP_ERR_NO_MEM;
    }

    memset(epd->framebuffer, 0xFF, FRAMEBUFFER_SIZE);

    // Display initialisieren (hängt BUSY, ist das Display defekt oder nicht angeschlossen)
    ret = init_sequence(epd);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Display reagiert nicht (BUSY-Timeout)");
        epd_bw_deinit(epd);
        spi_bus_remove_device(epd->spi);
        spi_bus_free(host);
        return ret;
    }

    ESP_LOGI(TAG, "Initialisierung abgeschlossen");
    return ESP_OK;
}

void epd_bw_fill(epd_bw_t* epd, uint8_t color)
{
    uint8_t fill_value = (color == EPD_BW_WHITE) ? 0xFF : 0x00;
    memset(epd->framebuffer, fill_value, FRAMEBUFFER_SIZE);

    if (epd->debug)
    {
        ESP_LOGI(TAG, "Fülle mit %s", (color == EPD_BW_WHITE) ? "Weiß" : "Schwarz");
    }
}

void epd_bw_draw_pixel(epd_bw_t* epd, int x, int y, uint8_t color)
{
    // Logische in physische Koordinaten umrechnen
    int phys_x, phys_y;
    transform_coords(epd, x, y, &phys_x, &phys_y);

    // Grenzen prüfen
    if (phys_x < 0 || phys_x >= EPD_PHYS_WIDTH || phys_y < 0 || phys_y >= EPD_PHYS_HEIGHT)
    {
        return;
    }

    // Pixel im Framebuffer setzen
    uint32_t byte_idx = (phys_y * (EPD_PHYS_WIDTH / 8)) + (phys_x / 8);
    uint8_t  bit_mask = 1 << (7 - (phys_x % 8));

    if (color == EPD_BW_BLACK)
    {
        epd->framebuffer[byte_idx] &= ~bit_mask;
    }
    else
    {
        epd->framebuffer[byte_idx] |= bit_mask;
    }
}

esp_err_t epd_bw_update(epd_bw_t* epd)
{
    esp_err_t ret = init_sequence(epd);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Display reagiert nicht, Update abgebrochen");
        return ret;
    }

    // RAM beschreiben (BW-Daten)
    send_command(epd, 0x24);

    const uint16_t bytes_per_line = EPD_PHYS_WIDTH / 8;

    for (int y = 0; y < EPD_PHYS_HEIGHT; y++)
    {
        send_data(epd, &epd->framebuffer[y * bytes_per_line], bytes_per_line);
    }

    // Update auslösen
    send_command(epd, 0x22);
    send_data_byte(epd, 0xF7);
    send_command(epd, 0x20);

    wait_busy(epd, "Vollständiges Update");
    epd_bw_sleep(epd);

    if (epd->debug)
    {
        ESP_LOGI(TAG, "Vollständiges Update abgeschlossen");
    }

    return ESP_OK;
}

void epd_bw_update_window(epd_bw_t* epd, uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
    if (x >= epd->width || y >= epd->height || w == 0 || h == 0)
    {
        return;
    }

    // Clipping
    if (x + w > epd->width)
    {
        w = epd->width - x;
    }
    if (y + h > epd->height)
    {
        h = epd->height - y;
    }

    // Logische Ecken in physische Bounding Box umrechnen
    int px1, py1, px2, py2;
    transform_coords(epd, x, y, &px1, &py1);
    transform_coords(epd, x + w - 1, y + h - 1, &px2, &py2);

    // Bounding Box normalisieren
    if (px1 > px2)
    {
        int tmp = px1;
        px1     = px2;
        px2     = tmp;
    }
    if (py1 > py2)
    {
        int tmp = py1;
        py1     = py2;
        py2     = tmp;
    }

    uint16_t xs = px1 / 8;
    uint16_t xe = px2 / 8;
    uint16_t ys = py1;
    uint16_t ye = py2;

    if (epd->debug)
    {
        ESP_LOGI(TAG, "Partielles Update: log(%d,%d,%d,%d) -> phys x=%d-%d y=%d-%d", x, y, w, h, xs * 8, xe * 8 + 7, ys, ye);
    }

    software_reset(epd);

    // Border Waveform für partielles Update
    send_command(epd, 0x3C);
    send_data_byte(epd, 0x80);

    // RAM-Bereich setzen
    send_command(epd, 0x44);
    send_data_byte(epd, xs);
    send_data_byte(epd, xe);

    send_command(epd, 0x45);
    send_data_byte(epd, ys & 0xFF);
    send_data_byte(epd, (ys >> 8) & 0xFF);
    send_data_byte(epd, ye & 0xFF);
    send_data_byte(epd, (ye >> 8) & 0xFF);

    // RAM-Pointer setzen
    send_command(epd, 0x4E);
    send_data_byte(epd, xs);
    send_command(epd, 0x4F);
    send_data_byte(epd, ys & 0xFF);
    send_data_byte(epd, (ys >> 8) & 0xFF);

    // RAM1 beschreiben (BW-Daten)
    send_command(epd, 0x24);
    for (uint16_t row = ys; row <= ye; row++)
    {
        for (uint16_t col = xs; col <= xe; col++)
        {
            uint32_t idx   = row * (EPD_PHYS_WIDTH / 8) + col;
            uint8_t  value = (idx < FRAMEBUFFER_SIZE) ? epd->framebuffer[idx] : 0xFF;
            send_data_byte(epd, value);
        }
    }

    // RAM2 mit gleichen Daten beschreiben (lt. Hersteller-Code)
    send_command(epd, 0x26);
    for (uint16_t row = ys; row <= ye; row++)
    {
        for (uint16_t col = xs; col <= xe; col++)
        {
            uint32_t idx   = row * (EPD_PHYS_WIDTH / 8) + col;
            uint8_t  value = (idx < FRAMEBUFFER_SIZE) ? epd->framebuffer[idx] : 0xFF;
            send_data_byte(epd, value);
        }
    }

    // Partielles Update auslösen
    send_command(epd, 0x22);
    send_data_byte(epd, 0xFF);
    send_command(epd, 0x20);

    wait_busy(epd, "Partielles Update");
    epd_bw_sleep(epd);
}

void epd_bw_sleep(epd_bw_t* epd)
{
    send_command(epd, 0x02);
    wait_busy(epd, "Power Off");

    send_command(epd, 0x10);
    send_data_byte(epd, 0x01);
}

void epd_bw_deinit(epd_bw_t* epd)
{
    if (epd->framebuffer)
    {
        free(epd->framebuffer);
        epd->framebuffer = NULL;
    }
}