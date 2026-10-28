from deskai.terminal import _weather_answer, _weather_location_from_prompt


def test_weather_location_preserves_user_detail() -> None:
    assert _weather_location_from_prompt("weather of coventry, rhode island") == (
        "coventry, rhode island"
    )
    assert _weather_location_from_prompt("What's the weather in Plano Texas?") == (
        "Plano Texas"
    )


def test_non_weather_prompt_is_not_precalled() -> None:
    assert _weather_location_from_prompt("Tell me the history of Coventry") is None


def test_weather_answer_uses_provider_data_without_simulation_claim() -> None:
    answer = _weather_answer(
        {
            "status": "ok",
            "error": None,
            "data": {
                "resolved": True,
                "location": {"label": "Coventry, Rhode Island, United States"},
                "current": {
                    "condition": "Overcast",
                    "temperature_f": 55.2,
                    "temperature_c": 12.9,
                    "feels_like_f": 50.7,
                    "feels_like_c": 10.4,
                    "relative_humidity_percent": 45,
                    "wind_kmh": 4.6,
                    "precipitation_mm": 0.0,
                },
                "daily": [],
                "attribution": "Weather data by Open-Meteo.",
                "retrieved_at": "2026-10-28T17:00:00Z",
            },
        }
    )

    assert "Coventry, Rhode Island" in answer
    assert "55.2 °F" in answer
    assert "simulated" not in answer.casefold()
