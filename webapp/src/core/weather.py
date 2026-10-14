# src/core/weather.py
# Wetter-Integration: ruft aktuelle Wetterdaten per Open-Meteo-API ab.
import time
import logging
import httpx

logger = logging.getLogger("Weather")

# Cache: {(lat, lon): {"data": {...}, "fetched_at": timestamp}}
_cache = {}
CACHE_TTL = 1800  # 30 Minuten
# Zeitlimit pro Anfrage. Der BLE-Worker wartet ohnehin nur kurz auf das Wetter,
# ein späterer Abruf füllt den Cache für den nächsten Kontakt.
HTTP_TIMEOUT_S = 5.0

# Geocoding-Cache: {ortsname: (lat, lon)}. Ohne ihn würde jede Messung eines
# Outdoor-Geräts mit Ortsnamen die Koordinaten neu abfragen.
_geo_cache = {}


async def fetch_weather(lat: float, lon: float) -> dict | None:
    """
    Holt aktuelle Wetterdaten + Stundenvorhersage von Open-Meteo.

    Returns:
        dict mit Keys: temperature, humidity, precipitation_now,
        precipitation_next_1h, precipitation_next_3h, precipitation_next_6h,
        weather_code, wind_speed
        Oder None bei Fehler.
    """
    cache_key = (round(lat, 2), round(lon, 2))

    # Cache prüfen
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached["fetched_at"]) < CACHE_TTL:
        return cached["data"]

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "hourly": "precipitation",
            "forecast_hours": 6,
            "timezone": "auto",
        }

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()

        current = raw.get("current", {})
        hourly = raw.get("hourly", {})
        precip_hours = hourly.get("precipitation", [])

        # Niederschlag der nächsten Stunden summieren
        precip_1h = sum(precip_hours[:1]) if len(precip_hours) >= 1 else 0
        precip_3h = sum(precip_hours[:3]) if len(precip_hours) >= 3 else 0
        precip_6h = sum(precip_hours[:6]) if len(precip_hours) >= 6 else 0

        data = {
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation_now": current.get("precipitation", 0),
            "precipitation_next_1h": precip_1h,
            "precipitation_next_3h": precip_3h,
            "precipitation_next_6h": precip_6h,
            "weather_code": current.get("weather_code", 0),
            "wind_speed": current.get("wind_speed_10m", 0),
        }

        _cache[cache_key] = {"data": data, "fetched_at": time.time()}
        logger.info(f"Wetter geladen für ({lat}, {lon}): {data['temperature']}°C, "
                     f"Regen 1h: {precip_1h}mm")
        return data

    except Exception as e:
        logger.error(f"Wetter-Abfrage fehlgeschlagen: {e}")
        return None


async def geocode(location_str: str) -> tuple[float, float] | None:
    """
    Löst einen Ortsnamen in Koordinaten auf via Open-Meteo Geocoding API.

    Returns:
        (latitude, longitude) oder None
    """
    key = location_str.strip().lower()
    if key in _geo_cache:
        return _geo_cache[key]

    try:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": location_str, "count": 1, "language": "de"}

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            raw = resp.json()

        results = raw.get("results", [])
        if results:
            r = results[0]
            # Nur Treffer merken: Fehler können vorübergehend sein
            _geo_cache[key] = (r["latitude"], r["longitude"])
            return _geo_cache[key]
        return None

    except Exception as e:
        logger.error(f"Geocoding fehlgeschlagen für '{location_str}': {e}")
        return None


async def get_weather_for_device(device_settings: dict) -> dict | None:
    """
    Holt Wetterdaten für ein Gerät basierend auf seinen Standort-Einstellungen.
    Unterstützt sowohl Koordinaten als auch Ortsnamen.

    Args:
        device_settings: dict mit 'type' und 'location' Keys

    Returns:
        Wetterdaten-dict oder None (bei Indoor oder fehlendem Standort)
    """
    if device_settings.get("type") != "outdoor":
        return None

    location = device_settings.get("location")
    if not location:
        return None

    # Prüfe ob location bereits Koordinaten sind (Format: "lat,lon")
    if isinstance(location, dict) and "lat" in location and "lon" in location:
        return await fetch_weather(location["lat"], location["lon"])

    if isinstance(location, str):
        # Versuche als "lat,lon" zu parsen
        parts = location.split(",")
        if len(parts) == 2:
            try:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                return await fetch_weather(lat, lon)
            except ValueError:
                pass

        # Sonst als Ortsname geocoden
        coords = await geocode(location)
        if coords:
            return await fetch_weather(coords[0], coords[1])

    return None
