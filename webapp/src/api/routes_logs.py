# src/api/routes_logs.py
# REST-Endpunkte für System-Logs: liefert Log-Einträge an das Frontend.
from fastapi import APIRouter

router = APIRouter()

# Wird in main.py gesetzt
log_store = None


@router.get("/logs")
def get_logs(limit: int = 200, mac: str = None, level: str = None):
    return log_store.get_logs(limit=limit, mac=mac, level=level)
