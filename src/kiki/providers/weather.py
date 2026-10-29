from __future__ import annotations

from datetime import UTC, datetime
import re
from random import random
from time import monotonic, sleep
from typing import Any, Callable, Protocol

import httpx

from ..resilience import CircuitBreaker, KikiError, ErrorCode


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


class HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, url: str, *, params: dict[str, Any]) -> HttpResponse: ...


class WeatherProvider(Protocol):
    def get_weather(
        self, location: str, country_code: str = "US", days: int = 3
    ) -> dict[str, Any]: ...


class OpenMeteoWeatherProvider:
    """Bounded Open-Meteo adapter with fixed endpoints and short-lived caching."""

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        cache_seconds: float = 600,
        stale_seconds: float = 3600,
        max_attempts: int = 3,
        base_delay: float = 0.25,
        sleeper: Callable[[float], None] = sleep,
        random_source: Callable[[], float] = random,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.client = client or httpx.Client(
            timeout=10,
            headers={"User-Agent": "Kiki/0.1 (local personal assistant)"},
        )
        self.cache_seconds = cache_seconds
        self.stale_seconds = max(stale_seconds, cache_seconds)
        self.max_attempts = max(1, max_attempts)
        self.base_delay = max(0.0, base_delay)
        self._sleep = sleeper
        self._random = random_source
        self.circuit_breaker = circuit_breaker or CircuitBreaker("Open-Meteo")
        self._cache: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}

    def get_weather(
        self, location: str, country_code: str = "US", days: int = 3
    ) -> dict[str, Any]:
        original_location = location.strip()
        location, country_code = _normalize_us_location(location, country_code)
        key = (location.casefold(), country_code, days)
        cached = self._cache.get(key)
        if cached and monotonic() - cached[0] <= self.cache_seconds:
            return {**cached[1], "cached": True}
        try:
            matches = self._geocode(location, country_code)
            if not matches:
                return {
                    "resolved": False,
                    "needs_clarification": True,
                    "message": f"No location matched {original_location!r} in {country_code}.",
                    "choices": [],
                    "provider": "Open-Meteo",
                }

            plausible = _plausible_matches(location, matches)
            if len(plausible) != 1:
                return {
                    "resolved": False,
                    "needs_clarification": True,
                    "message": "The location is ambiguous; use City, State or a more specific postal code.",
                    "choices": [_location_choice(match) for match in plausible[:5]],
                    "provider": "Open-Meteo",
                }

            selected = plausible[0]
            forecast = self._forecast(selected, days)
            result = {
                "resolved": True,
                "needs_clarification": False,
                "location": _location_choice(selected),
                **forecast,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "cached": False,
                "stale": False,
                "provider": "Open-Meteo",
                "attribution": "Weather data by Open-Meteo.com (CC BY 4.0); location data by GeoNames.",
            }
            self._cache[key] = (monotonic(), result)
            return result
        except (KikiError, OSError, ValueError):
            if cached and monotonic() - cached[0] <= self.stale_seconds:
                return {
                    **cached[1],
                    "cached": True,
                    "stale": True,
                    "warning": "Live weather is unavailable; showing the most recent cached result.",
                }
            raise

    def _geocode(self, location: str, country_code: str) -> list[dict[str, Any]]:
        payload = self._request_json(
            GEOCODING_URL,
            {
                "name": location.strip(),
                "count": 5,
                "language": "en",
                "format": "json",
                "countryCode": country_code.upper(),
            },
        )
        results = payload.get("results", [])
        return results if isinstance(results, list) else []

    def _forecast(self, location: dict[str, Any], days: int) -> dict[str, Any]:
        latitude = _number(location, "latitude")
        longitude = _number(location, "longitude")
        payload = self._request_json(
            FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "timezone": "auto",
                "forecast_days": days,
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "precipitation,weather_code,wind_speed_10m"
                ),
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,precipitation_sum"
                ),
                "temperature_unit": "celsius",
            },
        )
        current = payload.get("current")
        daily = payload.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise KikiError(
                "Open-Meteo returned an incomplete forecast",
                code=ErrorCode.PROVIDER_RESPONSE,
            )

        current_c = _number(current, "temperature_2m")
        apparent_c = _number(current, "apparent_temperature")
        dates = _list(daily, "time")
        highs = _list(daily, "temperature_2m_max")
        lows = _list(daily, "temperature_2m_min")
        codes = _list(daily, "weather_code")
        precip_chance = _list(daily, "precipitation_probability_max")
        precip_sum = _list(daily, "precipitation_sum")
        count = min(len(dates), len(highs), len(lows), len(codes), len(precip_chance), len(precip_sum))

        return {
            "timezone": payload.get("timezone", location.get("timezone")),
            "current": {
                "time": current.get("time"),
                "condition": _weather_description(int(_number(current, "weather_code"))),
                "temperature_c": round(current_c, 1),
                "temperature_f": round(_fahrenheit(current_c), 1),
                "feels_like_c": round(apparent_c, 1),
                "feels_like_f": round(_fahrenheit(apparent_c), 1),
                "relative_humidity_percent": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "wind_kmh": current.get("wind_speed_10m"),
            },
            "daily": [
                {
                    "date": dates[index],
                    "condition": _weather_description(int(codes[index])),
                    "high_c": round(float(highs[index]), 1),
                    "high_f": round(_fahrenheit(float(highs[index])), 1),
                    "low_c": round(float(lows[index]), 1),
                    "low_f": round(_fahrenheit(float(lows[index])), 1),
                    "precipitation_probability_percent": precip_chance[index],
                    "precipitation_mm": precip_sum[index],
                }
                for index in range(count)
            ],
        }

    def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        self.circuit_breaker.allow()
        for attempt in range(self.max_attempts):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise KikiError(
                        "Open-Meteo returned a malformed response",
                        code=ErrorCode.PROVIDER_RESPONSE,
                    )
                if payload.get("error"):
                    raise KikiError(
                        str(payload.get("reason", "Provider rejected the request")),
                        code=ErrorCode.PROVIDER_RESPONSE,
                    )
                self.circuit_breaker.success()
                return payload
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status not in {408, 429, 500, 502, 503, 504}:
                    self.circuit_breaker.failure()
                    raise KikiError(
                        f"Open-Meteo rejected the request (HTTP {status})",
                        code=ErrorCode.PROVIDER_RESPONSE,
                    ) from exc
                last_error = exc
            except KikiError:
                self.circuit_breaker.failure()
                raise
            if attempt + 1 < self.max_attempts:
                self._sleep(self._retry_delay(attempt, last_error))
        self.circuit_breaker.failure()
        code = (
            ErrorCode.RATE_LIMITED
            if isinstance(last_error, httpx.HTTPStatusError)
            and last_error.response.status_code == 429
            else ErrorCode.TIMEOUT
            if isinstance(last_error, httpx.TimeoutException)
            else ErrorCode.SERVICE_UNAVAILABLE
        )
        raise KikiError(
            "Open-Meteo timed out or could not be reached",
            code=code,
            retryable=True,
        ) from last_error

    def _retry_delay(self, attempt: int, error: Exception | None) -> float:
        if isinstance(error, httpx.HTTPStatusError):
            retry_after = error.response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(10.0, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        exponential = self.base_delay * (2**attempt)
        return min(5.0, exponential + exponential * 0.25 * self._random())


def _plausible_matches(location: str, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requested = location.split(",", 1)[0].strip().casefold()
    exact = [
        match
        for match in matches
        if str(match.get("name", "")).casefold() == requested
        or requested in {str(code).casefold() for code in match.get("postcodes", [])}
    ]
    if exact:
        return exact
    return matches


def _normalize_us_location(location: str, country_code: str) -> tuple[str, str]:
    """Expand U.S. postal abbreviations so geocoding does not treat them as name text."""
    location = location.strip()
    country_code = country_code.strip().upper()

    # Small models sometimes put a state abbreviation in the country field.
    if country_code in US_STATES:
        state = US_STATES[country_code]
        if state.casefold() not in location.casefold():
            location = f"{location}, {state}"
        country_code = "US"

    if country_code == "US":
        if "," not in location:
            lowered = location.casefold()
            for state in sorted(US_STATES.values(), key=len, reverse=True):
                suffix = f" {state.casefold()}"
                if lowered.endswith(suffix) and len(location) > len(suffix):
                    location = f"{location[:-len(suffix)].strip()}, {state}"
                    break
        match = re.fullmatch(r"(.+?)(?:,|\s)\s*([A-Za-z]{2})", location)
        if match and match.group(2).upper() in US_STATES:
            location = f"{match.group(1).strip()}, {US_STATES[match.group(2).upper()]}"
    return location, country_code


def _location_choice(location: dict[str, Any]) -> dict[str, Any]:
    parts = [location.get("name"), location.get("admin1"), location.get("country")]
    return {
        "id": location.get("id"),
        "label": ", ".join(str(part) for part in parts if part),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "timezone": location.get("timezone"),
        "country_code": location.get("country_code"),
    }


def _number(mapping: dict[str, Any], key: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)):
        raise KikiError(
            f"Open-Meteo response omitted {key}",
            code=ErrorCode.PROVIDER_RESPONSE,
        )
    return float(value)


def _list(mapping: dict[str, Any], key: str) -> list[Any]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise KikiError(
            f"Open-Meteo response omitted {key}",
            code=ErrorCode.PROVIDER_RESPONSE,
        )
    return value


def _fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def _weather_description(code: int) -> str:
    if code == 0:
        return "Clear sky"
    if code in (1, 2, 3):
        return "Partly cloudy" if code < 3 else "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return f"Weather code {code}"
