# main.py - elHydro Web Application
# FastAPI-Hauptanwendung: bindet alle Router ein und startet den BLE-Worker.
import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.core.data_manager import DataManager
from src.core.brain import Brain
from src.ble.ble_worker import BleWorker
from src.api.ws import ws_manager, router as ws_router
from src.api import routes_devices, routes_measurements, routes_logs
from src.core.log_store import LogStore
from src.utils.constants import LOG_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

data_manager = DataManager()
brain = Brain()
log_store = LogStore(LOG_FILE)

# Dependency Injection für API-Module
routes_devices.data_manager = data_manager
routes_measurements.data_manager = data_manager
routes_logs.log_store = log_store


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: BLE Worker als Background-Task starten
    async def broadcast_with_logging(event: str, data: dict):
        await ws_manager.broadcast(event, data)
        if event == "log":
            log_store.append(data.get("message", ""), level="INFO", mac=data.get("mac"))
        elif event == "alert":
            log_store.append(data.get("message", ""), level="WARNING", mac=data.get("mac"))
        elif event == "data_received":
            mac = data.get("mac", "")
            log_store.append(f"Messdaten empfangen", level="INFO", mac=mac)
        elif event == "brain_decision":
            mac = data.get("mac", "")
            log_store.append(
                f"Brain: sleep={data.get('sleep_s')}s, irrigate={data.get('irrigate')}",
                level="INFO", mac=mac,
            )

    worker = BleWorker(data_manager, brain, broadcast_with_logging)
    app.state.ble_worker = worker
    task = asyncio.create_task(worker.run())
    logging.info("elHydro Web gestartet - http://0.0.0.0:8000")
    yield
    # Shutdown
    worker.running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logging.info("elHydro Web beendet")


app = FastAPI(title="elHydro", lifespan=lifespan)

# API Routen
app.include_router(routes_devices.router, prefix="/api")
app.include_router(routes_measurements.router, prefix="/api")
app.include_router(routes_logs.router, prefix="/api")
app.include_router(ws_router)

# Statische Dateien (Frontend)
app.mount("/static", StaticFiles(directory="static"), name="static-files")


# SPA Catch-All: unbekannte Pfade liefern index.html
@app.get("/{path:path}")
async def spa_fallback(request: Request, path: str):
    import os
    static_file = os.path.join("static", path)
    if os.path.isfile(static_file):
        return FileResponse(static_file)
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="elHydro Web Server")
    parser.add_argument("--port", type=int, default=8000, help="Port (Standard: 8000)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (Standard: 0.0.0.0)")
    args = parser.parse_args()
    uvicorn.run("main:app", host=args.host, port=args.port, reload=False)
