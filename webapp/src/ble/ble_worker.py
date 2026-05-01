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
    UUID_SVC_CUSTOM, UUID_CHR_MEAS, UUID_CHR_TIME,
    UUID_CHR_SLEEP, UUID_CHR_TARGET, UUID_CHR_OFFLINE_SLEEP,
    UUID_CHR_IRRIGATION, UUID_CHR_IRR_DELTA,
    DEVICE_NAME, load_plant_presets,
)
from src.ble.parser import MeasurementParser
from src.core.weather import get_weather_for_device
from src.core.brain import COOLDOWN_SECONDS, MIN_SLEEP_S

logger = logging.getLogger("BleWorker")

# Maximale Wartezeit auf Messungen (Sekunden)
RECEIVE_TIMEOUT_S = 20


class BleWorker:
    def __init__(self, data_manager, brain,
                 broadcast_fn: Callable[[str, dict], Awaitable]):
        self.data_manager = data_manager
        self.brain = brain
        self.broadcast = broadcast_fn
        self.running = True

    async def run(self):
        await self.broadcast("log", {"message": "BLE Scanner gestartet..."})
        while self.running:
            try:
                scan_results = await BleakScanner.discover(
                    timeout=4.0, return_adv=True
                )

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
                logger.error(f"Scanner Fehler: {e}")
                await self.broadcast("log", {"message": f"Scanner Fehler: {e}"})
                await asyncio.sleep(2.0)

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

                # First-Setup-Sonderpfad: ESP ist in STATE_FIRST_SETUP und sendet
                # noch keine Messung. Phase 1 würde 20 s in den Timeout laufen.
                # Direkt Phase 3 senden, die Messung kommt nach dem kurzen Deep
                # Sleep im nächsten Connect-Zyklus.
                device = self.data_manager.get_device(mac)
                first_setup = device.get("first_setup", {}) if device else {}
                is_first_setup = not first_setup.get("completed", True)

                if is_first_setup:
                    await self.broadcast("log", {
                        "message": "First-Setup erkannt: Phase 1 übersprungen, sende Konfiguration direkt"
                    })
                    await self._send_all_commands(client, mac, decision=None)
                else:
                    # ── Phase 1: Empfang ─────────────────────────────────────
                    # Notifications sofort starten (kein Delay!)
                    buffered, online_measurement = await self._receive_measurements(
                        client, mac
                    )

                    # Timestamps rekonstruieren (offline-Messungen rückrechnen)
                    self.data_manager.reconstruct_timestamps(buffered, online_measurement)

                    # Historie VOR dem Schreiben der gepufferten Messungen holen,
                    # damit history[-1] immer der letzte abgeschlossene Zyklus ist
                    history = self.data_manager.get_history(mac, limit=10)

                    # Gepufferte Messungen in CSV schreiben (jetzt mit korrekten Timestamps)
                    for m in buffered:
                        self.data_manager.append_measurement(mac, m)

                    # ── Phase 2: Verarbeitung ────────────────────────────────
                    decision = None
                    if online_measurement:
                        decision = await self._process_smart_logic(
                            mac, online_measurement, history
                        )
                        # Online-Messung erst nach Brain-Entscheidung in CSV
                        # schreiben, damit brain_sleep_s etc. enthalten sind
                        self.data_manager.append_measurement(mac, online_measurement)

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

    async def _receive_measurements(self, client, mac):
        """
        Empfängt alle Messungen von der Firmware.

        Gepufferte Messungen (online=0) werden gesammelt (nicht sofort geschrieben),
        damit Timestamps nachträglich rekonstruiert werden können.
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

        await client.start_notify(UUID_CHR_MEAS, notification_handler)
        await self.broadcast("log", {"message": "Notifications aktiv, empfange Daten..."})

        # Auf Messungen warten bis online=1 kommt oder Timeout
        deadline = asyncio.get_event_loop().time() + RECEIVE_TIMEOUT_S
        while asyncio.get_event_loop().time() < deadline:
            if not client.is_connected:
                break

            try:
                parsed = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )

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

        if not online_measurement:
            await self.broadcast("log", {
                "message": "Keine aktuelle Messung empfangen (nur gepufferte oder Timeout)"
            })

        return buffered_measurements, online_measurement

    # =====================================================================
    # Phase 2: Verarbeitung - Smart-Logic
    # =====================================================================

    async def _process_smart_logic(self, mac, parsed, history):
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
            weather_data = await get_weather_for_device(dev)
            if weather_data:
                self.data_manager.settings[mac]["last_weather"] = {
                    **weather_data,
                    "fetched_at": int(time.time()),
                }
                self.data_manager.save_settings()
                await self.broadcast("log", {
                    "message": f"Wetter: {weather_data.get('temperature')}°C, "
                               f"Regen 1h: {weather_data.get('precipitation_next_1h', 0)}mm"
                })

        # Plant-Multiplier aus Preset holen
        plant_multiplier = self._get_plant_multiplier(
            dev.get("plant_type", "Standard (Normal)")
        )

        # Vorherige Messung für Trend-Erkennung (history wurde VOR dem
        # Schreiben gepufferter Messungen geholt → [-1] ist letzter Zyklus)
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

    def _get_plant_multiplier(self, plant_type_name):
        """Holt den numerischen Multiplikator für einen Pflanzentyp."""
        presets = load_plant_presets()
        for p in presets:
            if p.get("name") == plant_type_name:
                return p.get("sleep_multiplier", 1.0)
        return 1.0
