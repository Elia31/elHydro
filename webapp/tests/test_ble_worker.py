# Tests für die Auswertung empfangener Messungen im BLE-Worker (ohne Bluetooth)
import asyncio
import struct
import time
from types import SimpleNamespace

import main
from src.ble import ble_worker
from src.ble.ble_worker import BleWorker
from src.ble.parser import MeasurementParser
from src.core.brain import Brain
from src.utils.constants import (
    UUID_CHR_MEAS, UUID_CHR_MEAS_IND, UUID_CHR_OFFLINE_SLEEP, UUID_CHR_SLEEP,
    UUID_CHR_TARGET, UUID_CHR_TIME,
)


class Recorder:
    """Ersetzt den WebSocket-Broadcast und merkt sich alle Events."""

    def __init__(self):
        self.events = []

    async def __call__(self, event, data):
        self.events.append((event, data))

    def alerts(self):
        return [data["type"] for event, data in self.events if event == "alert"]


def make_worker(mac):
    main.data_manager.add_or_update_device(mac, "Test", "standard", False)
    recorder = Recorder()
    return BleWorker(main.data_manager, Brain(), recorder), recorder


def test_dry_pump_is_reported_until_irrigation_works():
    mac = "AA:BB:CC:DD:EE:10"
    worker, recorder = make_worker(mac)

    asyncio.run(worker._update_pump_state(mac, [{"irrigated": True, "pump_dry": True}]))
    assert main.data_manager.get_device(mac)["pump_dry"] is True
    assert recorder.alerts() == ["pump_dry"]

    # Gleicher Zustand: keine zweite Meldung, Messungen ohne Bewässerung ändern nichts
    asyncio.run(worker._update_pump_state(mac, [{"irrigated": False}, {"irrigated": True, "pump_dry": True}]))
    assert recorder.alerts() == ["pump_dry"]

    asyncio.run(worker._update_pump_state(mac, [{"irrigated": True, "pump_dry": False}]))
    assert main.data_manager.get_device(mac)["pump_dry"] is False


def test_brain_uses_buffered_measurements():
    # Nach dem Gießen puffert der Knoten die Kontrollmessung. Der Trend der nächsten
    # Messung muss mit ihr verglichen werden, nicht mit dem Wert vor dem Gießen.
    mac = "AA:BB:CC:DD:EE:11"
    worker, _ = make_worker(mac)
    now = int(time.time())
    main.data_manager.append_measurement(mac, {"timestamp": now - 3600, "soil_pct": 30, "online": True})
    buffered = [{"timestamp": now - 1800, "soil_pct": 50, "online": False, "irrigated": True}]
    online = {"timestamp": now, "soil_pct": 49, "temp": 20.0, "rh": 80.0, "online": True}

    decision = asyncio.run(worker._process_measurements(mac, buffered, online))

    assert "Feuchte steigt" not in decision.reasoning
    assert [r["soil_pct"] for r in main.data_manager.get_history(mac)] == [30, 50, 49]


def make_outdoor_worker(mac, weather_fn, monkeypatch):
    monkeypatch.setattr(ble_worker, "get_weather_for_device", weather_fn)
    main.data_manager.add_or_update_device(mac, "Test", "standard", True, "Berlin")
    return BleWorker(main.data_manager, Brain(), Recorder())


def dry_measurement():
    return {"timestamp": 0, "soil_pct": 20, "temp": 15.0, "rh": 80.0, "online": True}


def test_weather_fetched_on_connect_is_used(monkeypatch):
    async def rain(dev):
        return {"temperature": 15.0, "humidity": 80,
                "precipitation_next_1h": 0, "precipitation_next_3h": 6}

    mac = "AA:BB:CC:DD:EE:12"
    worker = make_outdoor_worker(mac, rain, monkeypatch)

    async def sync():
        # Wie in connect_and_sync: Abruf beim Verbinden starten, danach auswerten
        task = worker._start_weather_fetch(main.data_manager.get_device(mac))
        return await worker._process_measurements(mac, [], dry_measurement(), task)

    decision = asyncio.run(sync())

    assert not decision.should_irrigate
    assert "Regen" in decision.reasoning
    assert main.data_manager.get_device(mac)["last_weather"]["precipitation_next_3h"] == 6


def test_slow_weather_does_not_block_decision(monkeypatch):
    # Die Firmware wartet nur 10 s auf die Befehle. Hängt der Wetterabruf,
    # entscheidet das Brain nach WEATHER_WAIT_S ohne Wetter.
    async def hanging(dev):
        await asyncio.sleep(30)

    monkeypatch.setattr(ble_worker, "WEATHER_WAIT_S", 0.1)
    mac = "AA:BB:CC:DD:EE:13"
    worker = make_outdoor_worker(mac, hanging, monkeypatch)

    start = time.monotonic()
    decision = asyncio.run(worker._process_measurements(mac, [], dry_measurement()))

    assert time.monotonic() - start < 5
    assert decision.should_irrigate
    assert "last_weather" not in main.data_manager.get_device(mac)


def packed_measurement(measurement_id, soil_pct, online):
    """Messung im Binärformat der Firmware (siehe parser.py)."""
    return struct.pack(
        MeasurementParser.FMT,
        measurement_id, 21.5, 55.0, soil_pct, 1500, 0, 0, 0, 3.9, int(online), 8,
        45, 10, 14400, 2600, 800, 5, 2.5, 100.0, 0, 1000, 2000, 3600, 7200, 200000, 0,
    )


class FakeNode:
    """Ersetzt BleakClient: Ein Knoten, der nach dem Abonnieren seine Messungen sendet."""

    def __init__(self, payloads, indications=True):
        self.payloads = payloads
        self.indications = indications
        self.subscribed = None
        self.writes = {}
        self.is_connected = True
        self.services = self

    def get_characteristic(self, uuid):
        return uuid == UUID_CHR_MEAS_IND and self.indications

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def start_notify(self, uuid, handler):
        self.subscribed = uuid
        for payload in self.payloads:
            handler(None, bytearray(payload))

    async def write_gatt_char(self, uuid, data, response=True):
        self.writes[uuid] = data


def sync_with(node, mac, monkeypatch):
    monkeypatch.setattr(ble_worker, "BleakClient", lambda device, **kwargs: node)
    worker = BleWorker(main.data_manager, Brain(), Recorder())
    asyncio.run(worker.connect_and_sync(SimpleNamespace(address=mac)))


def test_registered_node_that_is_already_set_up_keeps_its_data(monkeypatch):
    # Neuer Host oder Gerät neu hinzugefügt: Der Knoten ist schon eingerichtet und
    # schickt sofort Puffer und aktuelle Messung. Die dürfen nicht verworfen werden.
    mac = "AA:BB:CC:DD:EE:14"
    main.data_manager.add_or_update_device(mac, "Test", "standard", False)
    node = FakeNode([packed_measurement(41, 50, online=False), packed_measurement(42, 48, online=True)])

    sync_with(node, mac, monkeypatch)

    assert [r["measurement_id"] for r in main.data_manager.get_history(mac)] == [41, 42]
    assert UUID_CHR_SLEEP in node.writes and UUID_CHR_TIME in node.writes
    assert main.data_manager.get_device(mac)["first_setup"]["completed"]


def test_node_in_first_setup_gets_its_configuration(monkeypatch):
    monkeypatch.setattr(ble_worker, "SETUP_PROBE_S", 0.1)
    mac = "AA:BB:CC:DD:EE:15"
    main.data_manager.add_or_update_device(mac, "Test", "standard", False)
    node = FakeNode([])

    sync_with(node, mac, monkeypatch)

    assert main.data_manager.get_history(mac) == []
    assert {UUID_CHR_TARGET, UUID_CHR_OFFLINE_SLEEP, UUID_CHR_TIME} <= node.writes.keys()
    assert UUID_CHR_SLEEP not in node.writes
    assert main.data_manager.get_device(mac)["first_setup"]["completed"]


def test_indications_are_used_when_the_firmware_offers_them(monkeypatch):
    for indications, expected in ((True, UUID_CHR_MEAS_IND), (False, UUID_CHR_MEAS)):
        mac = "AA:BB:CC:DD:EE:16"
        main.data_manager.add_or_update_device(mac, "Test", "standard", False)
        node = FakeNode([packed_measurement(1, 50, online=True)], indications=indications)
        sync_with(node, mac, monkeypatch)
        assert node.subscribed == expected
