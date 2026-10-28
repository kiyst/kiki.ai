from deskai.terminal import (
    TerminalSession,
    _handle_command,
    _choice_query,
    _select_weather_choice,
    _weather_answer,
    _weather_location_from_prompt,
)
from deskai.model_client import ChatOutcome
from rich.console import Console


class ChoiceWeather:
    def get_weather(
        self, location: str, country_code: str = "US", days: int = 3
    ) -> dict[str, object]:
        if location.casefold() == "ohio":
            return {
                "resolved": False,
                "message": "The location is ambiguous.",
                "choices": [
                    {"label": "Ohio, Illinois, United States"},
                    {"label": "Ohio, Georgia, United States"},
                ],
            }
        return {
            "resolved": True,
            "location": {"label": "Ohio, Illinois, United States"},
            "current": {
                "condition": "Clear sky",
                "temperature_f": 72.0,
                "temperature_c": 22.2,
                "feels_like_f": 70.0,
                "feels_like_c": 21.1,
                "relative_humidity_percent": 50,
                "wind_kmh": 10.0,
                "precipitation_mm": 0.0,
            },
            "daily": [],
            "attribution": "Weather data by Open-Meteo.",
            "retrieved_at": "now",
        }


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


def test_weather_choice_accepts_state_name_number_and_ordinal() -> None:
    choices = [
        {"label": "Ohio, Illinois, United States"},
        {"label": "Ohio, Georgia, United States"},
    ]

    assert _select_weather_choice("Illinois", choices) == choices[0]
    assert _select_weather_choice("2", choices) == choices[1]
    assert _select_weather_choice("first", choices) == choices[0]
    assert _choice_query(choices[0]) == "Ohio, Illinois"


def test_weather_choice_rejects_shared_or_unknown_component() -> None:
    choices = [
        {"label": "Ohio, Illinois, United States"},
        {"label": "Ohio, Georgia, United States"},
    ]

    assert _select_weather_choice("Ohio", choices) is None
    assert _select_weather_choice("6", choices) is None


def test_session_uses_followup_to_select_pending_weather_choice(tmp_path) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    session.weather = ChoiceWeather()

    first, _ = session.ask("what's the weather in Ohio")
    second, _ = session.ask("Illinois")

    assert "Possible matches" in first.answer
    assert second.trace[0].arguments == {"location": "Ohio, Illinois"}
    assert "Ohio, Illinois, United States" in second.answer
    assert session.pending_weather_choices == []


def test_retry_copy_sources_and_transcript_workflow(tmp_path, monkeypatch) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    outcome = ChatOutcome(
        "A useful answer.",
        [],
        [{"source_id": "abc", "path": "notes.md", "citation": "[source:abc] notes.md (lines 1-2)"}],
    )
    session._remember("Original prompt", outcome, "none")
    console = Console(record=True, width=100)
    copied: list[str] = []
    monkeypatch.setattr("deskai.terminal.pyperclip.copy", copied.append)

    _handle_command(console, session, "/copy")
    _handle_command(console, session, "/sources")
    transcript = tmp_path / "saved conversation.md"
    _handle_command(console, session, f'/save "{transcript}"')
    should_exit, retried = _handle_command(console, session, "/retry")

    assert should_exit is False
    assert retried == "Original prompt"
    assert session.histories["chat"] == []
    assert session.turns == []
    assert copied == ["A useful answer."]
    assert "Original prompt" in transcript.read_text(encoding="utf-8")
    assert "source:abc" in transcript.read_text(encoding="utf-8")


def test_new_command_clears_active_conversation(tmp_path) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    session._remember("hello", ChatOutcome("hi", [], []), "none")

    _handle_command(Console(), session, "/new")

    assert session.histories["chat"] == []
    assert session.last_prompts["chat"] is None
    assert session.turns == []
