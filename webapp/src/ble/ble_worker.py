# src/ble/ble_worker.py
# BLE-Worker: scannt nach Geräten, liest Sensordaten und sendet Bewässerungsbefehle.
import asyncio
import datetime
import struct
import logging
import time
from typing import Callable, Awaitable

from bleak import BleakScanner, BleakClient, BleakError

from src.utils.constants import (
    UUID_SVC_CUSTOM, UUID_CHR_MEAS, UUID_CHR_MEAS_IND, UUID_CHR_TIME,
    UUID_CHR_SLEEP, UUID_CHR_TARGET, UUID_CHR_OFFLINE_SLEEP,
    UUID_CHR_IRRIGATION, UUID_CHR_IRR_DELTA,
    DEVICE_NAME, load_plant_presets,
)
from src.ble.parser import MeasurementParser
from src.core.weather import get_weather_for_device
from src.core.brain import MIN_SLEEP_S

logger = logging.getLogger("BleWorker")

# Maximale Wartezeit auf die erste Messung nach dem Verbinden (Sekunden)
RECEIVE_TIMEOUT_S = 20
# Bei einem frisch registrierten Gerät: Ein schon eingerichteter Knoten sendet seine
# erste Messung direkt nach dem Verbinden, einer in der Ersteinrichtung gar keine
SETUP_PROBE_S = 3
# Maximale Pause zwischen zwei Messungen, solange der Knoten seinen Puffer nachsendet
RECEIVE_IDLE_TIMEOUT_S = 5
# Obergrenze für die gesamte Empfangsphase. Aktuelle Firmware löscht eine gepufferte
# Messung erst, wenn der Host den Empfang bestätigt hat (Indication). Was bis hierhin
# nicht ankommt, sendet sie beim nächsten Kontakt.
RECEIVE_MAX_S = 180
# Nach der aktuellen Messung wartet die Firmware höchstens 10 s auf die Befehle
# (BLE_COMMAND_TIMEOUT_MS). Das Wetter wird deshalb schon beim Verbinden abgerufen,
# und das Brain wartet danach höchstens so lange darauf (Sekunden).
WEATHER_WAIT_S = 3


class BleWorker:
    def __init__(self, data_manager, brain,
                 broadcast_fn: Callable[[str, dict], Awaitable]):
        self.data_manager = data_manager
        self.brain = brain
        self.broadcast = broadcast_fn
        self.running = True

    async def run(self):
        await self.broadcast("log", {"message": "BLE Scanner gestartet..."})
        error_delay = 2.0
        last_error = None
        while self.running:
            try:
                scan_results = await BleakScanner.discover(
                    timeout=4.0, return_adv=True
                )
                if last_error is not None:
                    await self.broadcast("log", {"message": "BLE Scanner läuft wieder"})
                    last_error = None
                    error_delay = 2.0

                for device, adv_data in scan_results.values():
                    name = device.name or adv_data.local_name or "Unbekannt"

                    is_ours = False
                    if UUID_SVC_CUSTOM.lower() in [
                        u.lower() for u in adv_data.service_uuids
                    ]:
                        is_ours = True
                    elif name == DEVICE_NAME:
                        is_ours = True

                    if is_ours:
                        await self.broadcast(
                            "device_found",
                            {"mac": device.address, "name": name,
                             "rssi": adv_data.rssi},
                        )

                        if self.data_manager.get_device(device.address):
                            await asyncio.sleep(0.5)
                            await self.connect_and_sync(device)

            except Exception as e:
                # Ohne Bluetooth scheitert jeder Scan: nur neue Fehler melden
                # und die Abstände bis 60 s verlängern, statt alle 3 s zu loggen
                if str(e) != last_error:
                    last_error = str(e)
                    logger.error(f"Scanner Fehler: {e}")
                    await self.broadcast("log", {"message": f"Scanner Fehler: {e}"})
                await asyncio.sleep(error_delay)
                error_delay = min(error_delay * 2, 60.0)

            await asyncio.sleep(1.0)

    async def connect_and_sync(self, device):
        """
        Verbindet sich mit dem ESP32 und synchronisiert Daten.

        Ablauf in 3 Phasen:
          Phase 1 (Empfang):  Notifications starten, alle Messungen empfangen
          Phase 2 (Logik):    Smart-Logic auf aktueller Messung (online=1)
          Phase 3 (Senden):   Config + Sleep + Irrigation + Time (letztes!)
        """
        mac = device.address
        await self.broadcast("log", {"message": f"Verbinde mit {mac}..."})

        try:
            async with BleakClient(
                device,
                timeout=10.0,
                winrt={"use_cached_services": False},
            ) as client:
                if not client.is_connected:
                    await self.broadcast(
                        "log", {"message": f"Konnte nicht verbinden mit {mac}"}
                    )
                    return

                await self.broadcast("device_connected", {"mac": mac})
                self.data_manager.update_last_seen(mac)

                # Frisch registriertes Gerät: Ein Knoten in der Ersteinrichtung sendet
                # keine Messung, sondern wartet nur auf die Konfiguration. Deshalb hier
                # nicht 20 s auf die erste Messung warten. War der Knoten aber schon
                # eingerichtet (neuer Host, Gerät gelöscht und neu hinzugefügt), schickt
                # er sofort seinen Puffer und die aktuelle Messung. Die werden ganz
                # normal gespeichert und ausgewertet, sonst gingen sie verloren.
                device = self.data_manager.get_device(mac)
                first_setup = device.get("first_setup", {}) if device else {}
                is_first_setup = not first_setup.get("completed", True)

                # Wetter parallel zum Empfang abrufen (siehe WEATHER_WAIT_S)
                weather_task = self._start_weather_fetch(device)

                # ── Phase 1: Empfang ─────────────────────────────────────
                # Notifications sofort starten (kein Delay!). Die Firmware liest
                # Befehle erst, wenn sie aktiv sind, auch in der Ersteinrichtung.
                buffered, online_measurement = await self._receive_measurements(
                    client, mac,
                    first_timeout_s=SETUP_PROBE_S if is_first_setup else RECEIVE_TIMEOUT_S,
                )
                if is_first_setup and not buffered and not online_measurement:
                    await self.broadcast("log", {
                        "message": "Knoten in der Ersteinrichtung, sende Konfiguration"
                    })

                # ── Phase 2: Verarbeitung ────────────────────────────────
                decision = await self._process_measurements(
                    mac, buffered, online_measurement, weather_task
                )

                # ── Phase 3: Senden ──────────────────────────────────────
                await self._send_all_commands(
                    client, mac, decision
                )

        except BleakError as e:
            logger.error(f"Bleak Fehler bei {mac}: {e}")
            await self.broadcast("log", {"message": f"BLE Fehler: {e}"})
        except Exception as e:
            logger.error(f"Allgemeiner Fehler bei {mac}: {e}")
            await self.broadcast("log", {"message": f"Fehler: {e}"})
        finally:
            await self.broadcast("device_disconnected", {"mac": mac})
            await self.broadcast("log", {"message": f"Getrennt von {mac}"})

    # =====================================================================
    # Phase 1: Empfang - Alle Messungen empfangen
    # =====================================================================

    async def _receive_measurements(self, client, mac, first_timeout_s=RECEIVE_TIMEOUT_S):
        """
        Empfängt alle Messungen von der Firmware.

        Gepufferte Messungen (online=0) werden gesammelt (nicht sofort geschrieben),
        damit Timestamps nachträglich rekonstruiert werden können.
        first_timeout_s: so lange wird auf die erste Messung gewartet.
        Gibt (buffered_list, online_measurement) zurück.
        """
        await self.broadcast("log", {"message": "Starte Notifications..."})

        online_measurement = None
        buffered_measurements = []
        queue: asyncio.Queue = asyncio.Queue()

        def notification_handler(sender, data):
            parsed = MeasurementParser.parse(data)
            if parsed:
                queue.put_nowait(parsed)

        # Neuere Firmware sendet die Messungen auch als Indication: Jede Messung wird
        # bestätigt, erst dann löscht der Knoten sie aus seinem Puffer
        if client.services.get_characteristic(UUID_CHR_MEAS_IND):
            await client.start_notify(UUID_CHR_MEAS_IND, notification_handler)
        else:
            await client.start_notify(UUID_CHR_MEAS, notification_handler)
        await self.broadcast("log", {"message": "Notifications aktiv, empfange Daten..."})

        # Auf Messungen warten bis online=1 kommt oder Timeout. Solange noch
        # gepufferte Messungen eintreffen, wird weiter gewartet: Ein fester
        # Timeout würde bei großem Puffer die letzten Messungen verlieren, weil
        # die Firmware sie nach dem Senden bereits gelöscht hat.
        loop = asyncio.get_running_loop()
        start = loop.time()
        deadline = start + first_timeout_s
        while loop.time() < deadline:
            if not client.is_connected:
                break

            try:
                parsed = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )
                deadline = min(loop.time() + RECEIVE_IDLE_TIMEOUT_S, start + RECEIVE_MAX_S)

                # Gepufferte Messungen sammeln (CSV-Schreiben nach Rekonstruktion)
                if not parsed["online"]:
                    buffered_measurements.append(parsed)

                # Alle Messungen per WebSocket senden
                await self.broadcast(
                    "data_received",
                    {"mac": mac, "measurement": parsed},
                )

                status = "ONLINE" if parsed["online"] else "gepuffert"
                await self.broadcast("log", {
                    "message": f"Messung ({status}): Boden {parsed['soil_pct']}%"
                })

                if parsed["online"]:
                    online_measurement = parsed
                    await self.broadcast("log", {
                        "message": "Aktuelle Messung empfangen - Empfangsphase abgeschlossen"
                    })
                    break

            except asyncio.TimeoutError:
                continue

        if not online_measurement and (buffered_measurements or first_timeout_s >= RECEIVE_TIMEOUT_S):
            await self.broadcast("log", {
                "message": "Keine aktuelle Messung empfangen (nur gepufferte oder Timeout)"
            })

        return buffered_measurements, online_measurement

    # =====================================================================
    # Phase 2: Verarbeitung - Speichern und Smart-Logic
    # =====================================================================

    async def _process_measurements(self, mac, buffered, online, weather_task=None):
        """
        Speichert die empfangenen Messungen und berechnet für die aktuelle
        Messung die Brain-Entscheidung. Gibt die BrainDecision zurück
        (None, wenn keine aktuelle Messung ankam).
        """
        # Timestamps rekonstruieren (offline-Messungen rückrechnen)
        self.data_manager.reconstruct_timestamps(buffered, online)

        # Gepufferte Messungen zuerst speichern: Sie sind neuer als alles in der CSV,
        # und das Brain soll Trend und Trocknungsrate auch aus ihnen berechnen
        # (z. B. aus der Kontrollmessung direkt nach einer Bewässerung)
        for m in buffered:
            self.data_manager.append_measurement(mac, m)

        await self._update_pump_state(mac, buffered + ([online] if online else []))

        if not online:
            return None

        history = self.data_manager.get_history(mac, limit=10)
        decision = await self._process_smart_logic(mac, online, history, weather_task)
        # Online-Messung erst nach Brain-Entscheidung in CSV
        # schreiben, damit brain_sleep_s etc. enthalten sind
        self.data_manager.append_measurement(mac, online)
        return decision

    async def _process_smart_logic(self, mac, parsed, history, weather_task=None):
        """
        Berechnet Smart Sleep und Bewässerungsentscheidung.
        Gibt die BrainDecision zurück.
        """
        dev = self.data_manager.get_device(mac)
        if not dev:
            return None

        config = dev.get("config", {})
        is_outdoor = dev.get("type") == "outdoor"

        # Wetter holen (nur Outdoor)
        weather_data = None
        if is_outdoor:
            weather_data = await self._await_weather(weather_task or self._start_weather_fetch(dev))
            if weather_data:
                self.data_manager.update_device(mac, last_weather={
                    **weather_data,
                    "fetched_at": int(time.time()),
                })
                await self.broadcast("log", {
                    "message": f"Wetter: {weather_data.get('temperature')}°C, "
                               f"Regen 1h: {weather_data.get('precipitation_next_1h', 0)}mm"
                })

        # Plant-Multiplier aus Preset holen
        plant_multiplier = self._get_plant_multiplier(dev.get("preset_id"))

        # Vorherige Messung für Trend-Erkennung (history enthält auch die gerade
        # empfangenen gepufferten Messungen → [-1] ist die Messung davor)
        previous_soil = None
        if len(history) >= 1:
            prev = history[-1]
            if isinstance(prev.get("soil_pct"), (int, float)):
                previous_soil = int(prev["soil_pct"])

        # Letzte Bewässerung für Cooldown
        last_irrigated_ts = dev.get("last_irrigated_ts", 0)

        # Brain-Entscheidung
        decision = self.brain.decide(
            device_config=config,
            plant_multiplier=plant_multiplier,
            is_outdoor=is_outdoor,
            current_soil=parsed["soil_pct"],
            current_temp=parsed["temp"],
            current_rh=parsed.get("rh"),
            weather_data=weather_data,
            last_irrigated_ts=last_irrigated_ts,
            previous_soil=previous_soil,
            history=history,
        )

        await self.broadcast("log", {
            "message": f"Brain: Sleep {decision.sleep_duration_s}s | "
                       f"Bewässerung {'JA' if decision.should_irrigate else 'NEIN'}"
        })
        await self.broadcast("log", {
            "message": f"Begründung: {decision.reasoning}"
        })

        # Brain-Daten in Measurement-Dict für CSV
        parsed["brain_sleep_s"] = decision.sleep_duration_s
        parsed["brain_irrigate"] = decision.should_irrigate
        parsed["brain_reasoning"] = decision.reasoning

        # Brain-Entscheidung per WebSocket senden
        await self.broadcast("brain_decision", {
            "mac": mac,
            "sleep_s": decision.sleep_duration_s,
            "irrigate": decision.should_irrigate,
            "reasoning": decision.reasoning,
            "alerts": decision.alerts,
        })

        # Alerts senden
        for alert in decision.alerts:
            await self.broadcast("alert", {
                "type": alert["type"],
                "mac": mac,
                "message": alert["message"],
            })

        return decision

    # =====================================================================
    # Phase 3: Senden - Alle Befehle an ESP32
    # =====================================================================

    async def _send_all_commands(self, client, mac, decision):
        """
        Sendet alle Befehle an den ESP32 in der richtigen Reihenfolge.
        Time-Sync wird als letztes gesendet (Firmware-Signal: "alles fertig").
        """
        if not client.is_connected:
            await self.broadcast("log", {"message": "Verbindung verloren, kann nicht senden"})
            return

        await self.broadcast("log", {"message": "Sende Befehle an ESP32..."})

        # 1. Config aus Pending-Queue
        await self._sync_config(client, mac)

        # 2. Sleep-Dauer aus Brain
        if decision:
            sleep_s = max(decision.sleep_duration_s, MIN_SLEEP_S)
            try:
                await client.write_gatt_char(
                    UUID_CHR_SLEEP,
                    struct.pack("<I", sleep_s),
                    response=True,
                )
                await self.broadcast("log", {
                    "message": f"Sleep gesendet: {sleep_s}s"
                })
                await asyncio.sleep(0.3)
            except Exception as e:
                await self.broadcast("log", {
                    "message": f"Fehler beim Senden von Sleep: {e}"
                })

        # 3. Bewässerung aus Brain
        if decision and decision.should_irrigate:
            try:
                await client.write_gatt_char(
                    UUID_CHR_IRRIGATION, struct.pack("<B", 1), response=True
                )
                await self.broadcast("log", {
                    "message": "Bewässerung ausgelöst!"
                })
                self.data_manager.set_last_irrigated(mac)
                await asyncio.sleep(0.3)
            except Exception as e:
                await self.broadcast("log", {
                    "message": f"Fehler Bewässerung: {e}"
                })

        # 4. Time-Sync als LETZTES (Firmware beendet wait_for_control)
        now_unix = int(datetime.datetime.now().timestamp())
        try:
            await client.write_gatt_char(
                UUID_CHR_TIME, struct.pack("<I", now_unix), response=True
            )
            self.data_manager.update_first_setup(mac, "time_sent")
            await self.broadcast("log", {
                "message": f"Zeit gesynct: {now_unix} (Sendephase abgeschlossen)"
            })
        except Exception as e:
            await self.broadcast("log", {
                "message": f"Fehler Zeit-Sync: {e}"
            })

    # =====================================================================
    # Hilfsmethoden
    # =====================================================================

    async def _sync_config(self, client, mac):
        """Sendet Konfiguration an das Gerät mit First-Setup-Tracking."""
        device = self.data_manager.get_device(mac)
        if not device:
            return

        pending = device.get("pending", {})
        current_config = device.get("config", {})
        first_setup = device.get("first_setup", {})
        is_first = not first_setup.get("completed", True)

        try:
            # Target Soil
            val = pending.get("target_soil_pct")
            if val is None:
                val = current_config.get("target_soil_pct")
            if val is not None:
                val = int(val)
                await client.write_gatt_char(
                    UUID_CHR_TARGET, struct.pack("<B", val), response=True
                )
                if pending.get("target_soil_pct") is not None:
                    self.data_manager.clear_pending(mac, "target_soil_pct")
                if is_first:
                    self.data_manager.update_first_setup(mac, "target_sent")
                await self.broadcast("log", {"message": f"Target Soil: {val}%"})
                await asyncio.sleep(0.3)

            # Irrigation Delta
            val = pending.get("irrigation_start_delta")
            if val is None:
                val = current_config.get("irrigation_start_delta")
            if val is not None:
                val = int(val)
                await client.write_gatt_char(
                    UUID_CHR_IRR_DELTA, struct.pack("<B", val), response=True
                )
                if pending.get("irrigation_start_delta") is not None:
                    self.data_manager.clear_pending(mac, "irrigation_start_delta")
                await self.broadcast("log", {"message": f"Irrigation Delta: {val}%"})
                await asyncio.sleep(0.3)

            # Offline Sleep
            val = pending.get("offline_sleep_s")
            if val is None:
                val = current_config.get("offline_sleep_s")
            if val is not None:
                val = int(val)
                await client.write_gatt_char(
                    UUID_CHR_OFFLINE_SLEEP, struct.pack("<I", val), response=True
                )
                if pending.get("offline_sleep_s") is not None:
                    self.data_manager.clear_pending(mac, "offline_sleep_s")
                if is_first:
                    self.data_manager.update_first_setup(mac, "offline_sleep_sent")
                await self.broadcast("log", {"message": f"Offline Sleep: {val}s"})
                await asyncio.sleep(0.3)

        except Exception as e:
            logger.error(f"Fehler Config Sync: {e}")
            await self.broadcast("log", {"message": f"Fehler Config Sync: {e}"})

    async def _update_pump_state(self, mac, measurements):
        """Wertet die Bewässerungen aus: Blieb der Boden trotz Pumpen trocken, meldet
        die Firmware pump_dry. Der Zustand gilt bis zur nächsten Bewässerung mit Wirkung."""
        for m in measurements:
            if not m.get("irrigated"):
                continue
            dry = bool(m.get("pump_dry"))
            if self.data_manager.set_pump_dry(mac, dry) and dry:
                await self.broadcast("alert", {
                    "type": "pump_dry",
                    "mac": mac,
                    "message": "Pumpe fördert kein Wasser, Tank leer?",
                })

    @staticmethod
    def _start_weather_fetch(dev):
        """Startet den Wetterabruf für ein Outdoor-Gerät als Task (sonst None)."""
        if not dev or dev.get("type") != "outdoor":
            return None
        return asyncio.create_task(get_weather_for_device(dev))

    async def _await_weather(self, task):
        """Wartet höchstens WEATHER_WAIT_S auf den Wetterabruf. Ein verspäteter Abruf
        läuft weiter und füllt den Cache für den nächsten Kontakt."""
        done, _ = await asyncio.wait({task}, timeout=WEATHER_WAIT_S)
        if task in done:
            try:
                return task.result()
            except Exception as e:
                # Ohne Wetter weiterentscheiden, statt den ganzen Sync abzubrechen
                logger.error(f"Wetter-Abruf fehlgeschlagen: {e}")
                return None
        await self.broadcast("log", {
            "message": f"Wetter nach {WEATHER_WAIT_S} s noch nicht geladen, entscheide ohne Wetter"
        })
        return None

    def _get_plant_multiplier(self, preset_id):
        """Holt den Schlaf-Multiplikator des Presets (1,0 ohne passendes Preset)."""
        presets = load_plant_presets()
        for p in presets:
            if p.get("id") == preset_id:
                return p.get("sleep_multiplier", 1.0)
        return 1.0
