/**
 * @file ble_link.c
 * @brief BLE-Kommunikationsschicht für elHydro
 */

#include "ble_link.h"

#include <string.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "host/ble_hs.h"
#include "host/ble_hs_mbuf.h"
#include "host/ble_uuid.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char* TAG = "BLE";

// ============================================================================
// UUIDs für GATT-Service und Charakteristiken
// ============================================================================
// Basis-UUID: 6E40xxxx-B5A3-F393-E0A9-E50E24DCCA9E
// Die letzten beiden Bytes vor 0x40 0x6E definieren die Charakteristik

static const ble_uuid128_t UUID_SVC_HYDRO =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x00, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_MEASUREMENT =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x01, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_TARGET_SOIL =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x02, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_SLEEP =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x03, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_OFFLINE_SLEEP =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x04, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_TIME =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x05, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_IRRIGATION =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x07, 0x40, 0x6E);

static const ble_uuid128_t UUID_CHR_IRR_DELTA =
    BLE_UUID128_INIT(0x9E, 0xCA, 0xDC, 0x24, 0x0E, 0xE5, 0xA9, 0xE0, 0x93, 0xF3, 0xA3, 0xB5, 0x40, 0x08, 0x40, 0x6E);

// ============================================================================
// Verbindungsparameter
// ============================================================================

static const struct ble_gap_upd_params CONNECTION_PARAMS = {
    .itvl_min            = 48, // Minimum Intervall: ~60 ms
    .itvl_max            = 96, // Maximum Intervall: ~120 ms
    .latency             = 0,
    .supervision_timeout = 1000, // Timeout: 10 s
};

// ============================================================================
// Interner Zustand
// ============================================================================

static bool s_initialized = false;

// Verbindung
static uint16_t s_conn_handle    = BLE_HS_CONN_HANDLE_NONE;
static bool     s_notify_enabled = false;

// GATT Handles
static uint16_t s_handle_measurement   = 0;
static uint16_t s_handle_target_soil   = 0;
static uint16_t s_handle_sleep         = 0;
static uint16_t s_handle_offline_sleep = 0;
static uint16_t s_handle_time          = 0;
static uint16_t s_handle_irrigation    = 0;
static uint16_t s_handle_irr_delta     = 0;

// Empfangene Steuerbefehle
static ble_link_control_t s_control = { 0 };

// Steuert, ob der GAP-Event-Handler nach Disconnect/Adv-Complete das
// Advertising automatisch neu starten darf. Wird via ble_link_stop() auf
// false gesetzt, damit ein gewollter Stop nicht sofort wieder advertised.
static volatile bool s_auto_restart_adv = true;

// Synchronisation
static SemaphoreHandle_t s_mutex        = NULL;
static SemaphoreHandle_t s_notify_mutex = NULL;
static SemaphoreHandle_t s_control_sem  = NULL;

// ============================================================================
// Vorwärtsdeklarationen
// ============================================================================

static void ble_host_task(void* param);
static void on_sync(void);
static int  gap_event_handler(struct ble_gap_event* event, void* arg);
static int  gatt_access_handler(uint16_t conn_handle, uint16_t attr_handle, struct ble_gatt_access_ctxt* ctxt, void* arg);

// ============================================================================
// Thread-sichere Hilfsfunktionen
// ============================================================================

static void set_notify_enabled(bool enabled)
{
    xSemaphoreTake(s_notify_mutex, portMAX_DELAY);
    s_notify_enabled = enabled;
    xSemaphoreGive(s_notify_mutex);
}

static bool get_notify_enabled(void)
{
    xSemaphoreTake(s_notify_mutex, portMAX_DELAY);
    bool enabled = s_notify_enabled;
    xSemaphoreGive(s_notify_mutex);
    return enabled;
}

// Setzt einen Kontrollwert und signalisiert dass neue Daten vorliegen
static void set_control_value(bool* flag, void* dest, const void* src, size_t len)
{
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(500)) != pdTRUE)
    {
        ESP_LOGE(TAG, "Mutex timeout in set_control_value");
        return;
    }
    memcpy(dest, src, len);
    *flag = true;
    xSemaphoreGive(s_mutex);
    xSemaphoreGive(s_control_sem);
}

static void set_irrigation_request(void)
{
    if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(500)) != pdTRUE)
    {
        ESP_LOGE(TAG, "Mutex timeout in set_irrigation_request");
        return;
    }
    s_control.have_irrigation_request = true;
    xSemaphoreGive(s_mutex);
    xSemaphoreGive(s_control_sem);
}

// ============================================================================
// GATT Access Handler
// ============================================================================

static int gatt_access_handler(uint16_t conn_handle, uint16_t attr_handle, struct ble_gatt_access_ctxt* ctxt, void* arg)
{
    (void) conn_handle;
    (void) arg;

    // Write-Operationen
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR)
    {
        if (attr_handle == s_handle_target_soil)
        {
            if (OS_MBUF_PKTLEN(ctxt->om) != sizeof(uint8_t))
            {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            uint8_t value;
            ble_hs_mbuf_to_flat(ctxt->om, &value, sizeof(value), NULL);
            if (value > 100)
            {
                value = 100;
            }
            set_control_value(&s_control.have_target_soil, &s_control.target_soil_pct, &value, sizeof(value));
            return 0;
        }

        if (attr_handle == s_handle_irr_delta)
        {
            if (OS_MBUF_PKTLEN(ctxt->om) != sizeof(uint8_t))
            {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            uint8_t value;
            ble_hs_mbuf_to_flat(ctxt->om, &value, sizeof(value), NULL);
            if (value < 1)
                value = 1;
            if (value > 100)
                value = 100;

            set_control_value(&s_control.have_irrigation_start_delta, &s_control.irrigation_start_delta, &value, sizeof(value));
            return 0;
        }

        if (attr_handle == s_handle_sleep)
        {
            if (OS_MBUF_PKTLEN(ctxt->om) != sizeof(uint32_t))
            {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            uint32_t value;
            ble_hs_mbuf_to_flat(ctxt->om, &value, sizeof(value), NULL);
            set_control_value(&s_control.have_sleep_s, &s_control.sleep_seconds, &value, sizeof(value));
            return 0;
        }

        if (attr_handle == s_handle_offline_sleep)
        {
            if (OS_MBUF_PKTLEN(ctxt->om) != sizeof(uint32_t))
            {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            uint32_t value;
            ble_hs_mbuf_to_flat(ctxt->om, &value, sizeof(value), NULL);
            set_control_value(&s_control.have_offline_sleep, &s_control.offline_sleep_s, &value, sizeof(value));
            return 0;
        }

        if (attr_handle == s_handle_time)
        {
            if (OS_MBUF_PKTLEN(ctxt->om) != sizeof(uint32_t))
            {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            uint32_t value;
            ble_hs_mbuf_to_flat(ctxt->om, &value, sizeof(value), NULL);
            set_control_value(&s_control.have_unix_time, &s_control.unix_time, &value, sizeof(value));
            return 0;
        }

        if (attr_handle == s_handle_irrigation)
        {
            if (OS_MBUF_PKTLEN(ctxt->om) != sizeof(uint8_t))
            {
                return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
            }
            uint8_t value;
            ble_hs_mbuf_to_flat(ctxt->om, &value, sizeof(value), NULL);
            if (value != 0)
            {
                ESP_LOGI(TAG, "Irrigation-Request empfangen");
                set_irrigation_request();
            }
            return 0;
        }

        return BLE_ATT_ERR_WRITE_NOT_PERMITTED;
    }
    return BLE_ATT_ERR_READ_NOT_PERMITTED;
}

// ============================================================================
// GATT Service Definition
// ============================================================================

// clang-format off
static const struct ble_gatt_svc_def GATT_SERVICES[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &UUID_SVC_HYDRO.u,
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                .uuid       = &UUID_CHR_MEASUREMENT.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &s_handle_measurement,
            },
            {
                .uuid       = &UUID_CHR_TARGET_SOIL.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_WRITE,
                .val_handle = &s_handle_target_soil,
            },
            {
                .uuid       = &UUID_CHR_SLEEP.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_WRITE,
                .val_handle = &s_handle_sleep,
            },
            {
                .uuid       = &UUID_CHR_OFFLINE_SLEEP.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_WRITE,
                .val_handle = &s_handle_offline_sleep,
            },
            {
                .uuid       = &UUID_CHR_TIME.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_WRITE,
                .val_handle = &s_handle_time,
            },
            {
                .uuid       = &UUID_CHR_IRRIGATION.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_WRITE,
                .val_handle = &s_handle_irrigation,
            },
            {
                .uuid       = &UUID_CHR_IRR_DELTA.u,
                .access_cb  = gatt_access_handler,
                .flags      = BLE_GATT_CHR_F_WRITE,
                .val_handle = &s_handle_irr_delta,
            },
            { 0 }
        },
    },
    { 0 }
};
// clang-format on

// ============================================================================
// GAP Event Handler
// ============================================================================

static int gap_event_handler(struct ble_gap_event* event, void* arg)
{
    (void) arg;

    switch (event->type)
    {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status == 0)
            {
                s_conn_handle = event->connect.conn_handle;
                ESP_LOGI(TAG, "Verbunden (handle=%d)", s_conn_handle);
                ble_gap_update_params(s_conn_handle, &CONNECTION_PARAMS);
            }
            else
            {
                ESP_LOGW(TAG, "Verbindung fehlgeschlagen (status=%d)", event->connect.status);
                s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
                if (s_auto_restart_adv)
                {
                    ble_link_start_advertising();
                }
            }
            break;

        case BLE_GAP_EVENT_DISCONNECT:
            ESP_LOGI(TAG, "Getrennt (reason=%d)", event->disconnect.reason);
            s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            set_notify_enabled(false);
            if (s_auto_restart_adv)
            {
                ble_link_start_advertising();
            }
            break;

        case BLE_GAP_EVENT_SUBSCRIBE:
            if (event->subscribe.attr_handle == s_handle_measurement)
            {
                bool enabled = (event->subscribe.cur_notify != 0);
                set_notify_enabled(enabled);
                ESP_LOGI(TAG, "Notifications %s", enabled ? "aktiviert" : "deaktiviert");
            }
            break;

        case BLE_GAP_EVENT_MTU:
            ESP_LOGI(TAG, "MTU: %d Bytes", event->mtu.value);
            break;

        case BLE_GAP_EVENT_CONN_UPDATE:
            ESP_LOGI(TAG, "Verbindungsparameter aktualisiert (status=%d)", event->conn_update.status);
            break;

        case BLE_GAP_EVENT_ADV_COMPLETE:
            ESP_LOGI(TAG, "Advertising beendet");
            if (s_auto_restart_adv)
            {
                ble_link_start_advertising();
            }
            break;

        default:
            break;
    }

    return 0;
}

// ============================================================================
// Stack-Synchronisation
// ============================================================================

static void on_sync(void)
{
    ESP_LOGI(TAG, "Stack synchronisiert");

    uint8_t addr_type;
    int     rc = ble_hs_id_infer_auto(0, &addr_type);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "Adresstyp konnte nicht ermittelt werden (rc=%d)", rc);
        return;
    }

    ble_link_start_advertising();
}

// ============================================================================
// NimBLE Host Task
// ============================================================================

static void ble_host_task(void* param)
{
    (void) param;
    nimble_port_run();
    nimble_port_freertos_deinit();
    vTaskDelete(NULL);
}

// ============================================================================
// Öffentliche API - Initialisierung
// ============================================================================

esp_err_t ble_link_init(const char* device_name)
{
    if (s_initialized)
    {
        return ESP_OK;
    }

    // NimBLE initialisieren
    int rc = nimble_port_init();
    if (rc != 0)
    {
        ESP_LOGE(TAG, "nimble_port_init fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    ble_svc_gap_init();
    ble_svc_gatt_init();

    // NVS-Store für Bonding initialisieren (vermeidet Warnungen)
    extern void ble_store_config_init(void);
    ble_store_config_init();

    // Gerätenamen setzen
    if (device_name && device_name[0])
    {
        ble_svc_gap_device_name_set(device_name);
    }
    else
    {
        ble_svc_gap_device_name_set("ESP32");
    }

    // GATT-Services registrieren
    rc = ble_gatts_count_cfg(GATT_SERVICES);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "ble_gatts_count_cfg fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    rc = ble_gatts_add_svcs(GATT_SERVICES);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "ble_gatts_add_svcs fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    // Callbacks setzen
    ble_hs_cfg.reset_cb = NULL;
    ble_hs_cfg.sync_cb  = on_sync;

    // Semaphore erstellen
    s_mutex        = xSemaphoreCreateMutex();
    s_notify_mutex = xSemaphoreCreateMutex();
    s_control_sem  = xSemaphoreCreateBinary();

    // MTU auf Maximum für BLE 4.2 setzen
    ble_att_set_preferred_mtu(247);

    // Host-Task starten
    nimble_port_freertos_init(ble_host_task);

    s_initialized = true;
    ESP_LOGI(TAG, "Initialisierung abgeschlossen");

    return ESP_OK;
}

// ============================================================================
// Öffentliche API - Advertising
// ============================================================================

esp_err_t ble_link_start_advertising(void)
{
    // Wieder freigeben fuer Auto-Restarts (falls vorher per ble_link_stop deaktiviert)
    s_auto_restart_adv = true;

    if (ble_gap_adv_active())
    {
        return ESP_OK;
    }

    // Advertisement-Daten: Flags und Name
    struct ble_hs_adv_fields adv_fields = { 0 };
    adv_fields.flags                    = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;

    const char* name            = ble_svc_gap_device_name();
    adv_fields.name             = (uint8_t*) name;
    adv_fields.name_len         = (uint8_t) strlen(name);
    adv_fields.name_is_complete = 1;

    int rc = ble_gap_adv_set_fields(&adv_fields);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "ble_gap_adv_set_fields fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    // Scan-Response: Service-UUID
    struct ble_hs_adv_fields rsp_fields = { 0 };
    rsp_fields.uuids128                 = (ble_uuid128_t*) &UUID_SVC_HYDRO;
    rsp_fields.num_uuids128             = 1;
    rsp_fields.uuids128_is_complete     = 1;

    rc = ble_gap_adv_rsp_set_fields(&rsp_fields);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "ble_gap_adv_rsp_set_fields fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    // Advertising starten
    uint8_t addr_type;
    rc = ble_hs_id_infer_auto(0, &addr_type);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "ble_hs_id_infer_auto fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    struct ble_gap_adv_params adv_params = { 0 };
    adv_params.conn_mode                 = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode                 = BLE_GAP_DISC_MODE_GEN;
    adv_params.itvl_min                  = 0x00A0; // ~100 ms
    adv_params.itvl_max                  = 0x00F0; // ~150 ms

    rc = ble_gap_adv_start(addr_type, NULL, BLE_HS_FOREVER, &adv_params, gap_event_handler, NULL);
    if (rc != 0)
    {
        ESP_LOGE(TAG, "ble_gap_adv_start fehlgeschlagen (rc=%d)", rc);
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Advertising gestartet");
    return ESP_OK;
}

esp_err_t ble_link_stop(void)
{
    // Auto-Restart unterdruecken, sonst startet der GAP-Event-Handler nach
    // dem ausgeloesten DISCONNECT sofort wieder Advertising.
    s_auto_restart_adv = false;

    // Verbindung trennen
    if (ble_link_is_connected())
    {
        ble_gap_terminate(s_conn_handle, BLE_ERR_REM_USER_CONN_TERM);
        vTaskDelay(pdMS_TO_TICKS(20));
    }

    // Advertising stoppen
    if (ble_gap_adv_active())
    {
        int rc = ble_gap_adv_stop();
        if (rc != 0 && rc != BLE_HS_EALREADY)
        {
            ESP_LOGW(TAG, "ble_gap_adv_stop fehlgeschlagen (rc=%d)", rc);
        }
    }

    s_conn_handle = BLE_HS_CONN_HANDLE_NONE;

    return ESP_OK;
}

// ============================================================================
// Öffentliche API - Verbindungsstatus
// ============================================================================

bool ble_link_is_connected(void)
{
    return s_conn_handle != BLE_HS_CONN_HANDLE_NONE;
}

bool ble_link_client_ready(void)
{
    return ble_link_is_connected() && get_notify_enabled();
}

// ============================================================================
// Öffentliche API - Datenübertragung
// ============================================================================

esp_err_t ble_link_notify_measurement(const measurement_t* measurement)
{
    if (!measurement)
    {
        return ESP_ERR_INVALID_ARG;
    }

    if (!ble_link_client_ready())
    {
        return ESP_ERR_INVALID_STATE;
    }

    // Direkt als Flat-Buffer in den mbuf kopieren und Notification senden
    struct os_mbuf* om = ble_hs_mbuf_from_flat(measurement, sizeof(*measurement));
    if (!om)
    {
        ESP_LOGE(TAG, "mbuf Allokation fehlgeschlagen");
        return ESP_ERR_NO_MEM;
    }

    int rc = ble_gatts_notify_custom(s_conn_handle, s_handle_measurement, om);
    if (rc != 0)
    {
        ESP_LOGW(TAG, "Notification fehlgeschlagen (rc=%d)", rc);
        os_mbuf_free_chain(om);
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Messung #%lu gesendet", (unsigned long) measurement->measurement_id);
    return ESP_OK;
}

// ============================================================================
// Öffentliche API - Steuerung
// ============================================================================

bool ble_link_wait_for_control(uint32_t timeout_ms, ble_link_control_t* out_ctrl)
{
    uint32_t deadline     = xTaskGetTickCount() + pdMS_TO_TICKS(timeout_ms);
    bool     received_any = false;

    // Warte auf Steuerbefehle bis Timeout
    while ((int32_t) (deadline - xTaskGetTickCount()) > 0)
    {
        if (!ble_link_is_connected())
        {
            break;
        }

        // Kurze Wartezeit damit mehrere Writes gesammelt werden können
        if (xSemaphoreTake(s_control_sem, pdMS_TO_TICKS(50)) == pdTRUE)
        {
            received_any = true;

            // Time Sync = letzter Befehl → sofort fertig
            if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(500)) != pdTRUE)
            {
                ESP_LOGE(TAG, "Mutex timeout in wait_for_control (done-check)");
                break;
            }
            bool done = s_control.have_unix_time;
            xSemaphoreGive(s_mutex);
            if (done)
            {
                break;
            }
        }
    }

    // Ergebnis kopieren und Flags zurücksetzen
    if (out_ctrl)
    {
        if (xSemaphoreTake(s_mutex, pdMS_TO_TICKS(500)) != pdTRUE)
        {
            ESP_LOGE(TAG, "Mutex timeout in wait_for_control (result copy)");
            return false;
        }
        *out_ctrl                             = s_control;
        s_control.have_target_soil            = false;
        s_control.have_irrigation_start_delta = false;
        s_control.have_sleep_s                = false;
        s_control.have_offline_sleep          = false;
        s_control.have_unix_time              = false;
        s_control.have_irrigation_request     = false;
        xSemaphoreGive(s_mutex);
    }

    return received_any;
}