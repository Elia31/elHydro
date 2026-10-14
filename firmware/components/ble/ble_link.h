/**
 * @file ble_link.h
 * @brief BLE-Kommunikationsschicht für elHydro
 *
 * Stellt einen GATT-Server mit Charakteristiken für Messdaten,
 * Konfiguration und Steuerung bereit. Kommuniziert mit der
 * Desktop-Anwendung während der kurzen Wach-Phasen.
 */

#ifndef BLE_LINK_H
#define BLE_LINK_H

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

// ============================================================================
// Datenstrukturen
// ============================================================================

// Messdatenstruktur für BLE-Übertragung
// Messdaten die per Notify an den PC gesendet werden
#include "measurement_types.h"

// Steuerbefehle die vom PC empfangen werden
typedef struct
{
    bool     have_unix_time;
    uint32_t unix_time;

    bool    have_target_soil;
    uint8_t target_soil_pct;

    bool    have_irrigation_start_delta;
    uint8_t irrigation_start_delta;

    bool     have_sleep_s;
    uint32_t sleep_seconds;

    bool     have_offline_sleep;
    uint32_t offline_sleep_s;

    bool have_irrigation_request;
} ble_link_control_t;

// ============================================================================
// Initialisierung und Lifecycle
// ============================================================================

// Initialisiert den BLE-Stack und registriert den GATT-Server
esp_err_t ble_link_init(const char* device_name);

// Startet das Advertising (wird automatisch nach Init aufgerufen)
esp_err_t ble_link_start_advertising(void);

// Stoppt BLE (Verbindung trennen, Advertising beenden)
esp_err_t ble_link_stop(void);

// ============================================================================
// Verbindungsstatus
// ============================================================================

// Prüft ob eine BLE-Verbindung besteht
bool ble_link_is_connected(void);

// Prüft ob Client verbunden UND Notifications oder Indications aktiviert hat
bool ble_link_client_ready(void);

// ============================================================================
// Datenübertragung
// ============================================================================

// Sendet eine Messung an den Host (nur wenn Client verbunden und subscribed).
// Hat der Host die Indication-Charakteristik abonniert, kommt ESP_OK erst nach seiner
// Bestätigung. Ältere Hosts abonnieren nur die Notify-Charakteristik, dann bedeutet
// ESP_OK nur "gesendet".
esp_err_t ble_link_send_measurement(const measurement_t* measurement);

// ============================================================================
// Steuerung empfangen
// ============================================================================

// Blockiert bis Steuerdaten empfangen wurden oder Timeout abläuft
// Gibt true zurück wenn mindestens ein Steuerbefehl empfangen wurde
bool ble_link_wait_for_control(uint32_t timeout_ms, ble_link_control_t* out_ctrl);

#endif // BLE_LINK_H