from __future__ import annotations

from typing import Any

import httpx
import pytest

from deskai.providers.weather import FORECAST_URL, GEOCODING_URL, OpenMeteoWeatherProvider


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> FakeResponse:
        self.calls.append((url, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _location(name: str, identifier: int, admin1: str = "New York") -> dict[str, Any]:
    return {
        "id": identifier,
        "name": name,
        "admin1": admin1,
        "country": "United States",
        "country_code": "US",
        "latitude": 40.7,
        "longitude": -74.0,
        "timezone": "America/New_York",
    }


def _forecast() -> dict[str, Any]:
    return {
        "timezone": "America/New_York",
        "current": {
            "time": "2026-10-28T10:00",
            "temperature_2m": 10.0,
            "apparent_temperature": 8.0,
            "relative_humidity_2m": 70,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 12.0,
        },
        "daily": {
            "time": ["2026-10-28"],
            "weather_code": [61],
            "temperature_2m_max": [15.0],
            "temperature_2m_min": [5.0],
            "precipitation_probability_max": [60],
            "precipitation_sum": [4.0],
        },
    }


def test_weather_resolves_and_returns_both_temperature_units() -> None:
    client = FakeHttpClient(
        [FakeResponse({"results": [_location("New York", 1)]}), FakeResponse(_forecast())]
    )
    provider = OpenMeteoWeatherProvider(client, cache_seconds=60)

    result = provider.get_weather("New York", "us", 1)
    cached = provider.get_weather("New York", "US", 1)

    assert result["resolved"] is True
    assert result["current"]["temperature_c"] == 10.0
    assert result["current"]["temperature_f"] == 50.0
    assert result["daily"][0]["high_f"] == 59.0
    assert result["attribution"].startswith("Weather data by Open-Meteo")
    assert cached["cached"] is True
    assert [call[0] for call in client.calls] == [GEOCODING_URL, FORECAST_URL]


def test_weather_returns_choices_for_ambiguous_location() -> None:
    client = FakeHttpClient(
        [
            FakeResponse(
                {
                    "results": [
                        _location("Springfield", 1, "Illinois"),
                        _location("Springfield", 2, "Massachusetts"),
                    ]
                }
            )
        ]
    )
    provider = OpenMeteoWeatherProvider(client)

    result = provider.get_weather("Springfield")

    assert result["resolved"] is False
    assert result["needs_clarification"] is True
    assert len(result["choices"]) == 2
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("location", "country_code"),
    [("Coventry RI", "US"), ("Coventry, RI", "US"), ("Coventry", "RI")],
)
def test_weather_normalizes_us_state_abbreviations(
    location: str, country_code: str
) -> None:
    client = FakeHttpClient(
        [
            FakeResponse({"results": [_location("Coventry", 1, "Rhode Island")]}),
            FakeResponse(_forecast()),
        ]
    )
    provider = OpenMeteoWeatherProvider(client)

    result = provider.get_weather(location, country_code, 1)

    assert result["resolved"] is True
    assert client.calls[0][1]["name"] == "Coventry, Rhode Island"
    assert client.calls[0][1]["countryCode"] == "US"


def test_weather_retries_transport_failure_then_reports_error() -> None:
    client = FakeHttpClient(
        [httpx.ReadTimeout("slow"), httpx.ConnectError("offline")]
    )
    provider = OpenMeteoWeatherProvider(client)

    with pytest.raises(OSError, match="timed out or could not connect"):
        provider.get_weather("Boston")

    assert len(client.calls) == 2
