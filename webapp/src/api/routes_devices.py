# src/api/routes_devices.py
# REST-Endpunkte für Geräteverwaltung: Einstellungen lesen, ändern und Geräte entfernen.
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

# Wird in main.py gesetzt
data_manager = None


class DeviceCreate(BaseModel):
    mac: str
    name: str
    plant_type: str
    is_outdoor: bool
    location: str | None = None


class DeviceSettings(BaseModel):
    target_soil_pct: int | None = Field(None, ge=0, le=100)
    irrigation_start_delta: int | None = Field(None, ge=0, le=100)
    offline_sleep_s: int | None = Field(None, ge=0, le=4294967295)
    plant_type: str | None = None
    type: str | None = None
    location: str | None = None


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
    data_manager.add_or_update_device(
        mac=body.mac,
        name=body.name,
        plant_type=body.plant_type,
        is_outdoor=body.is_outdoor,
        location=body.location,
    )
    return {"status": "ok", "mac": body.mac}


@router.put("/devices/{mac}/settings")
def update_settings(mac: str, body: DeviceSettings):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")

    # Config-Werte als pending queuen
    if body.target_soil_pct is not None:
        data_manager.update_and_queue(mac, "target_soil_pct", body.target_soil_pct)
    if body.irrigation_start_delta is not None:
        data_manager.update_and_queue(mac, "irrigation_start_delta", body.irrigation_start_delta)
    if body.offline_sleep_s is not None:
        data_manager.update_and_queue(mac, "offline_sleep_s", body.offline_sleep_s)
    # Metadaten direkt aktualisieren
    if body.plant_type is not None:
        data_manager.settings[mac]["plant_type"] = body.plant_type
    if body.type is not None:
        data_manager.settings[mac]["type"] = body.type
    if body.location is not None:
        data_manager.settings[mac]["location"] = body.location
    data_manager.save_settings()

    return {"status": "ok"}


class DeviceNotes(BaseModel):
    notes: str


@router.put("/devices/{mac}/notes")
def update_notes(mac: str, body: DeviceNotes):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    data_manager.settings[mac]["notes"] = body.notes
    data_manager.save_settings()
    return {"status": "ok"}


@router.delete("/devices/{mac}")
def delete_device(mac: str):
    dev = data_manager.get_device(mac)
    if not dev:
        raise HTTPException(status_code=404, detail="Gerät nicht gefunden")
    data_manager.delete_device(mac)
    return {"status": "ok"}
