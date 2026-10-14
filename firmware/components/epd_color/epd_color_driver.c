/**
 * @file epd_color_driver.c
 * @brief Treiber für 2.9" E-Paper Display (4-Farben)
 *
 * https://www.good-display.com/product/742.html
 * https://www.good-display.com/companyfile/1809.html
 */

#include "epd_color_driver.h"

#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char* TAG = "EPD_4C";

// ============================================================================
// Konstanten
// ============================================================================

// Framebuffer (2 Bit pro Pixel, 4 Pixel pro Byte)
#define PIXELS_PER_BYTE  4
#define FRAMEBUFFER_SIZE ((EPD_COLOR_PHYS_WIDTH * EPD_COLOR_PHYS_HEIGHT) / PIXELS_PER_BYTE)

// Timeout für BUSY-Pin (4-Farben-Updates sind langsam!)
#define BUSY_TIMEOUT_US 45000000 // 45 Sekunden

// Chunk-Größe für Datenübertragung
#define TRANSFER_CHUNK_SIZE 1024

// ============================================================================
// SPI-Kommunikation
// ============================================================================

static esp_err_t send_command(epd_color_t* epd, uint8_t cmd)
{
    gpio_set_level(epd->pin_dc, 0);
    spi_transaction_t t = { .length = 8, .tx_buffer = &cmd };
    return spi_device_transmit(epd->spi, &t);
}

static esp_err_t send_data(epd_color_t* epd, const void* data, size_t len)
{
    gpio_set_level(epd->pin_dc, 1);
    spi_transaction_t t = { .length = len * 8, .tx_buffer = data };
    return spi_device_transmit(epd->spi, &t);
}

static esp_err_t send_data_byte(epd_color_t* epd, uint8_t value)
{
    return send_data(epd, &value, 1);
}

// ============================================================================
// BUSY-Pin Handling
// ============================================================================
// Hinweis: Beim 4-Farben-Display ist BUSY=HIGH wenn bereit (invertiert zu BW!)

static esp_err_t wait_busy(epd_color_t* epd, const char* context)
{
    if (epd->debug)
    {
        ESP_LOGI(TAG, "Warte auf BUSY: %s", context);
    }

    int64_t start = esp_timer_get_time();

    // BUSY ist HIGH wenn Display bereit (invertiert zum BW-Display!)
    while (gpio_get_level(epd->pin_busy) != 1)
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

static void transform_coords(epd_color_t* epd, int x, int y, int* phys_x, int* phys_y)
{
    if (epd->upside_down)
    {
        // Querformat gedreht (ehem. ROT_270)
        *phys_x = EPD_COLOR_PHYS_WIDTH - 1 - y;
        *phys_y = x;
    }
    else
    {
        // Querformat normal (ehem. ROT_90)
        *phys_x = y;
        *phys_y = EPD_COLOR_PHYS_HEIGHT - 1 - x;
    }
}

// ============================================================================
// Hardware-Reset
// ============================================================================

static esp_err_t hardware_reset(epd_color_t* epd)
{
    vTaskDelay(pdMS_TO_TICKS(20));   // Warten vor Reset
    gpio_set_level(epd->pin_rst, 0); // Reset LOW
    vTaskDelay(pdMS_TO_TICKS(40));   // Reset halten
    gpio_set_level(epd->pin_rst, 1); // Reset HIGH
    vTaskDelay(pdMS_TO_TICKS(50));   // Stabilisieren
    return wait_busy(epd, "Hardware-Reset");
}

// ============================================================================
// JD79661 Initialisierungssequenz
// ============================================================================

static esp_err_t init_sequence(epd_color_t* epd)
{
    if (hardware_reset(epd) != ESP_OK)
    {
        return ESP_ERR_TIMEOUT;
    }

    // Power ON
    send_command(epd, 0x04);
    if (wait_busy(epd, "Power On") != ESP_OK)
    {
        return ESP_ERR_TIMEOUT;
    }

    // Panel Setting (PSR)
    send_command(epd, 0x4D);
    send_data_byte(epd, 0x78);

    send_command(epd, 0x00);
    send_data_byte(epd, 0x0F);
    send_data_byte(epd, 0x29);

    // Power Setting (PWRR)
    send_command(epd, 0x01);
    send_data_byte(epd, 0x07);
    send_data_byte(epd, 0x00);

    // Power Offset (POFS)
    send_command(epd, 0x03);
    send_data_byte(epd, 0x10);
    send_data_byte(epd, 0x54);
    send_data_byte(epd, 0x44);

    // Booster Soft Start (BTST)
    send_command(epd, 0x06);
    uint8_t btst[] = { 0x05, 0x00, 0x3F, 0x0A, 0x25, 0x12, 0x1A };
    send_data(epd, btst, sizeof(btst));

    // CDI Setting
    send_command(epd, 0x50);
    send_data_byte(epd, 0x37);

    // TCON Setting
    send_command(epd, 0x60);
    send_data_byte(epd, 0x02);
    send_data_byte(epd, 0x02);

    // Resolution (TRES)
    send_command(epd, 0x61);
    send_data_byte(epd, EPD_COLOR_PHYS_WIDTH / 256);
    send_data_byte(epd, EPD_COLOR_PHYS_WIDTH % 256);
    send_data_byte(epd, EPD_COLOR_PHYS_HEIGHT / 256);
    send_data_byte(epd, EPD_COLOR_PHYS_HEIGHT % 256);

    // Weitere Register (lt. Hersteller-Code)
    send_command(epd, 0xE7);
    send_data_byte(epd, 0x1C);

    send_command(epd, 0xE3);
    send_data_byte(epd, 0x22);

    send_command(epd, 0xB4);
    send_data_byte(epd, 0xD0);

    send_command(epd, 0xB5);
    send_data_byte(epd, 0x03);

    send_command(epd, 0xE9);
    send_data_byte(epd, 0x01);

    send_command(epd, 0x30);
    send_data_byte(epd, 0x08);

    return wait_busy(epd, "Init-Sequenz");
}

// ============================================================================
// Öffentliche API
// ============================================================================

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
    epd->fb_size     = FRAMEBUFFER_SIZE;

    // Immer Querformat
    epd->width  = EPD_COLOR_PHYS_HEIGHT;
    epd->height = EPD_COLOR_PHYS_WIDTH;

    ESP_LOGI(TAG,
             "Init: UpsideDown=%s, logisch=%dx%d, physisch=%dx%d, fb=%u Bytes",
             upside_down ? "ja" : "nein",
             epd->width,
             epd->height,
             EPD_COLOR_PHYS_WIDTH,
             EPD_COLOR_PHYS_HEIGHT,
             (unsigned) epd->fb_size);

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
    spi_bus_config_t bus_cfg = { .mosi_io_num = mosi, .miso_io_num = -1, .sclk_io_num = sclk, .max_transfer_sz = 8192 };

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
    epd->framebuffer = (uint8_t*) heap_caps_malloc(epd->fb_size, MALLOC_CAP_8BIT);
    if (!epd->framebuffer)
    {
        ESP_LOGE(TAG, "Framebuffer-Allokation fehlgeschlagen");
        spi_bus_remove_device(epd->spi);
        spi_bus_free(host);
        return ESP_ERR_NO_MEM;
    }

    // Mit Schwarz initialisieren (0x00 = alle Pixel schwarz)
    memset(epd->framebuffer, 0x00, epd->fb_size);

    // Display initialisieren (hängt BUSY, ist das Display defekt oder nicht angeschlossen)
    ret = init_sequence(epd);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Display reagiert nicht (BUSY-Timeout)");
        epd_color_deinit(epd);
        spi_bus_remove_device(epd->spi);
        spi_bus_free(host);
        return ret;
    }

    ESP_LOGI(TAG, "Initialisierung abgeschlossen");
    return ESP_OK;
}

void epd_color_fill(epd_color_t* epd, uint8_t color)
{
    // 4 Pixel pro Byte: 2-Bit Muster in alle 4 Slots replizieren
    uint8_t pattern    = (color & 0x03);
    uint8_t fill_value = (pattern << 6) | (pattern << 4) | (pattern << 2) | pattern;
    memset(epd->framebuffer, fill_value, epd->fb_size);
}

void epd_color_draw_pixel(epd_color_t* epd, int x, int y, uint8_t color)
{
    // Logische in physische Koordinaten umrechnen
    int phys_x, phys_y;
    transform_coords(epd, x, y, &phys_x, &phys_y);

    // Grenzen prüfen
    if (phys_x < 0 || phys_x >= EPD_COLOR_PHYS_WIDTH || phys_y < 0 || phys_y >= EPD_COLOR_PHYS_HEIGHT)
    {
        return;
    }

    // Pixel-Index berechnen (linear)
    uint32_t pixel_idx = (uint32_t) phys_y * EPD_COLOR_PHYS_WIDTH + (uint32_t) phys_x;

    // Byte-Index und Position im Byte (4 Pixel pro Byte)
    uint32_t byte_idx  = pixel_idx >> 2;
    uint8_t  pixel_pos = pixel_idx & 0x03; // 0..3

    // Bit-Shift berechnen (Pixel 0 → Bits 7:6, Pixel 3 → Bits 1:0)
    uint8_t shift = (3 - pixel_pos) * 2;
    uint8_t mask  = 0x03 << shift;
    uint8_t value = (color & 0x03) << shift;

    epd->framebuffer[byte_idx] = (epd->framebuffer[byte_idx] & ~mask) | value;
}

esp_err_t epd_color_update(epd_color_t* epd)
{
    esp_err_t ret = init_sequence(epd);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Display reagiert nicht, Update abgebrochen");
        return ret;
    }

    // Framebuffer zum Display übertragen (in Chunks)
    send_command(epd, 0x10);

    for (uint32_t offset = 0; offset < epd->fb_size; offset += TRANSFER_CHUNK_SIZE)
    {
        uint32_t len = TRANSFER_CHUNK_SIZE;
        if (offset + len > epd->fb_size)
        {
            len = epd->fb_size - offset;
        }
        send_data(epd, &epd->framebuffer[offset], len);
    }

    // Refresh auslösen
    send_command(epd, 0x12);
    send_data_byte(epd, 0x00);
    wait_busy(epd, "Refresh");

    // In Stromsparmodus wechseln
    epd_color_sleep(epd);

    if (epd->debug)
    {
        ESP_LOGI(TAG, "Vollständiges Update abgeschlossen");
    }

    return ESP_OK;
}

void epd_color_sleep(epd_color_t* epd)
{
    // Power Off
    send_command(epd, 0x02);
    send_data_byte(epd, 0x00);
    wait_busy(epd, "Power Off");

    // Deep Sleep
    send_command(epd, 0x07);
    send_data_byte(epd, 0xA5);
}

void epd_color_deinit(epd_color_t* epd)
{
    if (epd->framebuffer)
    {
        free(epd->framebuffer);
        epd->framebuffer = NULL;
    }
}