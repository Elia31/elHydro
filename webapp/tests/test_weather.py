# Tests für die Wetter-Anbindung (src/core/weather.py), ohne echte Netzwerkzugriffe
import asyncio

import pytest

from src.core import weather


class FakeClient:
    """Ersetzt httpx.AsyncClient und zählt die Anfragen."""
    calls = []
    response = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        FakeClient.calls.append(url)
        return FakeResponse(FakeClient.response)


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


@pytest.fixture
def fake_http(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(weather.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(weather, "_geo_cache", {})
    monkeypatch.setattr(weather, "_cache", {})
    return FakeClient


def test_geocode_is_cached(fake_http):
    fake_http.response = {"results": [{"latitude": 52.52, "longitude": 13.41}]}
    assert asyncio.run(weather.geocode("Berlin")) == (52.52, 13.41)
    assert asyncio.run(weather.geocode(" berlin ")) == (52.52, 13.41)
    assert len(fake_http.calls) == 1


def test_unknown_place_is_not_cached(fake_http):
    fake_http.response = {}
    assert asyncio.run(weather.geocode("Nirgendwo")) is None
    assert asyncio.run(weather.geocode("Nirgendwo")) is None
    assert len(fake_http.calls) == 2


def test_weather_sums_precipitation(fake_http):
    fake_http.response = {
        "current": {"temperature_2m": 18.0, "relative_humidity_2m": 60},
        "hourly": {"precipitation": [0.5, 1.0, 2.0, 0.0, 0.0, 3.0]},
    }
    data = asyncio.run(weather.get_weather_for_device({"type": "outdoor", "location": "52.5, 13.4"}))
    assert data["temperature"] == 18.0
    assert data["precipitation_next_1h"] == 0.5
    assert data["precipitation_next_3h"] == 3.5
    assert data["precipitation_next_6h"] == 6.5
    # Koordinaten direkt angegeben: kein Geocoding
    assert fake_http.calls == ["https://api.open-meteo.com/v1/forecast"]


def test_indoor_has_no_weather(fake_http):
    assert asyncio.run(weather.get_weather_for_device({"type": "indoor", "location": "Berlin"})) is None
    assert fake_http.calls == []
