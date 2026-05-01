/**
 * @file config.h
 * @brief System- und Laufzeitkonfiguration für elHydro
 *
 * Enthält alle konfigurierbaren Parameter die NICHT hardware-spezifisch sind:
 * Zeitfenster, Sleep-Dauer, NVS-Keys, Display-Einstellungen usw.
 * Hardware-Zuordnungen (GPIOs, Pins) befinden sich in pins.h
 */

#ifndef CONFIG_H
#define CONFIG_H

// ============================================================================
// Timing und Ablaufsteuerung
// ============================================================================

#define BLE_CONNECT_TIMEOUT_MS 15000           // Max. Wartezeit auf BLE-Verbindungsaufbau
#define BLE_COMMAND_TIMEOUT_MS 10000           // Max. Wartezeit auf Steuerbefehle nach Verbindung
#define BLE_POLL_MS            20              // Poll-Intervall beim Warten auf Verbindung
#define CALIBRATION_TIMEOUT_MS (5 * 60 * 1000) // Maximale Wartezeit bei Kalibrierung (5 Minuten)
#define VCC_INIT_TIME          100             // Stabilisierungszeit nach Sensor-Einschalten

// ============================================================================
// Bewässerungssteuerung
// ============================================================================

// Schrittweiten für adaptive Bewässerung
#define IRR_STEP_LARGE_MS 4000 // Wenn sehr trocken (>15% Diff zu Target Soil)
#define IRR_STEP_MED_MS   2000 // Wenn mittel trocken (>5% Diff zu Target Soil)
#define IRR_STEP_SMALL_MS 1000 // Wenn fast gut (<5% Diff zu Target Soil)

#define IRR_SOAK_MS      5000  // 5s warten (Sickerzeit)
#define IRR_MAX_TOTAL_MS 60000 // Maximale Gesamtgießzeit pro Zyklus (60s)

#define IRR_TARGET_TOLERANCE_PCT 2 // Akzeptable Abweichung zum Target Soil wo wir nicht nochmal gießen

// Schwellenwert-Sicherung: verhindert dass durch Fehlkonfiguration (großes Delta)
// die Bewässerung nie auslöst. Schwelle = max(target - delta, target * FACTOR/100, MIN_PCT)
#define IRR_THRESHOLD_MIN_PCT       5  // Absolutes Minimum (Schwelle fällt nie unter 5%)
#define IRR_THRESHOLD_TARGET_FACTOR 20 // Schwelle mind. 20% vom Target (skaliert mit Pflanze)

// ============================================================================
// Werksresetsteuerung
// ============================================================================

#define CALIBRATION_RESET_CLICK_COUNT    3     // Anzahl Hard-Resets zum Auslösen der Kalibrierungs-Sequenz
#define FACTORY_RESET_CLICK_COUNT        5     // Anzahl Hard-Resets zum Auslösen von Factory Reset
#define FACTORY_RESET_CONFIRM_TIMEOUT_MS 15000 // Zeitfenster für Bestätigung per Boot-Taste des Factory Reset (15s)

// ============================================================================
// Standardwerte (Fallback wenn keine Konfiguration vorhanden)
// ============================================================================

#define DEFAULT_TARGET_SOIL_PCT  50            // Ziel-Bodenfeuchte in Prozent
#define DEFAULT_IRRIGATION_DELTA 10            // Bewässerung wenn Target Soil um 10% unterschritten
#define DEFAULT_OFFLINE_SLEEP_S  (4 * 60 * 60) // Sleep-Dauer ohne BLE-Verbindung (4h)

// ============================================================================
// Bodenfeuchtesensor-Typ (genau einer muss aktiviert sein)
// ============================================================================

#define USE_LM393_SENSOR         0
#define USE_CAPACITIVE_V2_SENSOR 1

#if (USE_LM393_SENSOR + USE_CAPACITIVE_V2_SENSOR) != 1
    #error "Genau ein Sensor-Typ muss aktiviert sein!"
#endif

// Default-Kalibrierungswerte (abhängig vom Sensor-Typ)
#if USE_LM393_SENSOR
    #define DEFAULT_CALIB_RAW_DRY 3400
    #define DEFAULT_CALIB_RAW_WET 1300
#elif USE_CAPACITIVE_V2_SENSOR
    #define DEFAULT_CALIB_RAW_DRY 2600
    #define DEFAULT_CALIB_RAW_WET 800
#endif

// ============================================================================
// Display-Einstellungen
// ============================================================================

// Display-Typ Auswahl (genau ein Typ muss aktiviert sein)
#define USE_BW_DISPLAY     1
#define USE_BWR_DISPLAY    0
#define USE_4COLOR_DISPLAY 0

#if (USE_BW_DISPLAY + USE_BWR_DISPLAY + USE_4COLOR_DISPLAY) != 1
    #error "Genau ein Display-Typ muss aktiviert sein!"
#endif

// Display um 180° drehen (Querformat bleibt, aber gespiegelt)
// false = normal
// true  = gedreht
#define DISPLAY_UPSIDE_DOWN true

// extra Debug-Ausgaben für Display-Treiber
#define DISPLAY_DEBUG false

// Zeitzonen-Offset für Anzeige (Lokalzeit = UTC + Offset)
// MESZ (Sommerzeit): 2 * 3600, MEZ (Winterzeit): 1 * 3600
#define TIMEZONE_OFFSET_S (2 * 3600)

// Schwellwerte für Farbcodierung der Bodenfeuchte-Abweichung (in Prozentpunkten)
// clang-format off
#define DELTA_THRESHOLD_OK   5  // Bis 5% Abweichung: Schwarz (alles gut)
#define DELTA_THRESHOLD_WARN 10 // Bis 10% Abweichung: Gelb (Warnung)
                                // Darüber: Rot (kritisch)
// clang-format on

// ============================================================================
// NVS-Speicherung (Non-Volatile Storage)
// ============================================================================

#define NVS_NAMESPACE_APP "app" // Namespace für Einstellungen
#define NVS_NAMESPACE_BUF "buf" // Namespace für Messwert-Puffer

#define NVS_KEY_BLOB_CONFIG "blob_cfg"   // Einstellungen (Target, Sleep)
#define NVS_KEY_BLOB_CALIB  "blob_cal"   // Kalibrierung (Dry, Wet)
#define NVS_KEY_BLOB_STATE  "blob_sys"   // Systemzustand (IDs, Flags)
#define NVS_KEY_BLOB_STATS  "blob_stats" // Statistiken

// ============================================================================
// Offline-Puffer
// ============================================================================
// HINWEIS: MAX_BUFFER_ENTRIES haengt von der NVS-Partition-Groesse ab.
// Eine Messung (measurement_t) ist 80 B, mit NVS-Overhead ~128 B pro Eintrag:
//   24 KB NVS  -> max. ~150 Eintraege
//   256 KB NVS -> max. ~1700 Eintraege  (aktuelle Partition, siehe partitions.csv)
//   1 MB NVS   -> max. ~6500 Eintraege
#define MAX_BUFFER_ENTRIES 1000 // Maximale Anzahl gepufferter Messungen

// ============================================================================
// BLE Einstellungen
// ============================================================================

#define BLE_DEVICE_NAME "elHydro-ESP32C6"

#endif // CONFIG_H