# src/api/ws.py
# WebSocket-Verbindungsverwaltung: verwaltet aktive Clients und broadcastet Events.
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("WebSocket")

router = APIRouter()


class ConnectionManager:
    """Verwaltet alle aktiven WebSocket-Verbindungen."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info(f"WebSocket verbunden ({len(self.active)} aktiv)")

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
        logger.info(f"WebSocket getrennt ({len(self.active)} aktiv)")

    async def broadcast(self, event: str, data: dict):
        """Sendet ein Event an alle verbundenen Clients."""
        message = json.dumps({"event": event, "data": data}, default=str)
        disconnected = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


ws_manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Client-Nachrichten empfangen (z.B. start_scan, stop_scan)
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                event = msg.get("event")
                logger.info(f"WS Nachricht: {event}")
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
