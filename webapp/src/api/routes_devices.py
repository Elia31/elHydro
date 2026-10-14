# src/api/routes_devices.py
# REST-Endpunkte für Geräteverwaltung: Einstellungen lesen, ändern und Geräte entfernen.
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.utils.constants import (
    load_plant_presets, TARGET_SOIL_MIN, TARGET_SOIL_MAX, IRR_DELTA_MIN, IRR_DELTA_MAX,
)

router = APIRouter()

# Wird in main.py gesetzt
data_manager = None


# BLE-Adresse wie von bleak geliefert: MAC (Windows/Linux) oder UUID (macOS).
# Sie dient auch als Dateiname der Mess-CSV, deshalb nur dieses Format zulassen.
BLE_ADDRESS_PATTERN = (
    r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"
    r"|^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$"
)


class DeviceCreate(BaseModel):
    mac: str = Field(pattern=BLE_ADDRESS_PATTERN)
    name: str
    preset_id: str
    is_outdoor: bool
    location: str | None = None


class DeviceSettings(BaseModel):
    # Gleiche Grenzen wie Dashboard und Launcher (constants.py)
    target_soil_pct: int | None = Field(None, ge=TARGET_SOIL_MIN, le=TARGET_SOIL_MAX)
    irrigation_start_delta: int | None = Field(None, ge=IRR_DELTA_MIN, le=IRR_DELTA_MAX)
    # Gleiche Grenzen wie die Firmware: 10 min bis 24 h
    offline_sleep_s: int | None = Field(None, ge=600, le=86400)
    preset_id: str | None = None
    type: Literal["indoor", "outdoor"] | None = None
    location: str | None = None


def _check_preset(preset_id):
    if not any(p.get("id") == preset_id for p in load_plant_presets()):
        raise HTTPException(status_code=422, detail="Unbekanntes Preset")


@router.get("/devices")
def list_devices():
    devices = data_manager.get_all_devices()
    result = []
    for mac, dev in devices.items():
        result.append({"mac": mac, **dev})
    return result


@router.get("/devices/{mac}")
def get_device(mac: str):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")

    # Nächste Wachphase berechnen
    last_seen = dev.get("last_seen", 0)
    next_wake_ts = None
    if last_seen:
        history = data_manager.get_history(mac, limit=1)
        if history:
            brain_sleep_s = history[-1].get("brain_sleep_s")
            if brain_sleep_s:
                next_wake_ts = last_seen + int(brain_sleep_s)

    return {"mac": mac, "next_wake_ts": next_wake_ts, **dev}


@router.post("/devices")
def add_device(body: DeviceCreate):
    _check_preset(body.preset_id)
    data_manager.add_or_update_device(
        mac=body.mac,
        name=body.name,
        preset_id=body.preset_id,
        is_outdoor=body.is_outdoor,
        location=body.location,
    )
    return {"status": "ok", "mac": body.mac}


@router.put("/devices/{mac}/settings")
def update_settings(mac: str, body: DeviceSettings):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    # Ein inzwischen gelöschtes Preset darf stehen bleiben, nur neue werden geprüft
    if body.preset_id is not None and body.preset_id != dev.get("preset_id"):
        _check_preset(body.preset_id)

    # Config-Werte als pending queuen
    if body.target_soil_pct is not None:
        data_manager.update_and_queue(mac, "target_soil_pct", body.target_soil_pct)
    if body.irrigation_start_delta is not None:
        data_manager.update_and_queue(mac, "irrigation_start_delta", body.irrigation_start_delta)
    if body.offline_sleep_s is not None:
        data_manager.update_and_queue(mac, "offline_sleep_s", body.offline_sleep_s)
    # Metadaten direkt aktualisieren
    data_manager.update_device(
        mac, **body.model_dump(include={"preset_id", "type", "location"}, exclude_none=True)
    )

    return {"status": "ok"}


class DeviceNotes(BaseModel):
    notes: str


@router.put("/devices/{mac}/notes")
def update_notes(mac: str, body: DeviceNotes):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    data_manager.update_device(mac, notes=body.notes)
    return {"status": "ok"}


@router.delete("/devices/{mac}")
def delete_device(mac: str):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    data_manager.delete_device(mac)
    return {"status": "ok"}
