from kiki.terminal import (
    TerminalSession,
    _browse_path,
    _handle_command,
    _choice_query,
    _select_weather_choice,
    _weather_answer,
    _weather_location_from_prompt,
)
from kiki.model_client import ChatOutcome
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
    monkeypatch.setattr("kiki.terminal.pyperclip.copy", copied.append)

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


def test_memory_and_model_commands(tmp_path, monkeypatch) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    console = Console(record=True, width=100)
    monkeypatch.setenv("KIKI_MODEL_MAX", "large-code-model")

    _handle_command(console, session, "/remember I prefer Python")
    _handle_command(console, session, "/model max")
    answer, _ = session.ask("what do you remember")

    assert session.memory.notes() == ["I prefer Python"]
    assert session.model_profile == "max"
    assert "I prefer Python" in answer.answer


def test_diagnostics_omit_environment_values(tmp_path, monkeypatch) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    monkeypatch.setenv("KIKI_MODEL_MAX", "private-model-name")

    report = session.diagnostics()

    assert "environment" in report["note"].casefold()
    assert "private-model-name" not in str(report)
    assert report["tools"]["search_files"]["risk"] == "read_only"


def test_browser_gives_up_on_unreadable_root(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    def unreadable(self):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "iterdir", unreadable)
    root = Path(tmp_path.anchor)
    prompts = []

    selected = _browse_path(
        Console(record=True),
        root,
        purpose="database",
        default_filename=None,
        input_fn=lambda prompt: prompts.append(prompt) or "cancel",
    )

    assert selected is None
    assert prompts == []


def test_browser_selects_database_and_saves_here(tmp_path) -> None:
    (tmp_path / "books").mkdir()
    database = tmp_path / "books" / "history.sqlite3"
    database.write_bytes(b"")
    answers = iter(["1", "1"])

    selected = _browse_path(
        Console(record=True),
        tmp_path,
        purpose="database",
        default_filename=None,
        input_fn=lambda prompt: next(answers),
    )
    assert selected == database.resolve()

    answers = iter(["here notes"])
    saved = _browse_path(
        Console(record=True),
        tmp_path,
        purpose="save",
        default_filename="kiki.md",
        input_fn=lambda prompt: next(answers),
    )
    assert saved == tmp_path.resolve() / "notes.md"


def test_help_and_capabilities_keep_bracketed_arguments(tmp_path) -> None:
    console = Console(record=True, width=120)
    session = TerminalSession(tmp_path / "index.sqlite3")

    _handle_command(console, session, "/help")
    _handle_command(console, session, "/capabilities")
    rendered = console.export_text()

    for usage in ("/chat [message]", "/model [auto|fast|smart|max]", "/persona [show|reset]"):
        assert rendered.count(usage) == 2


def test_save_keeps_windows_backslashes_and_quoted_spaces(tmp_path) -> None:
    console = Console(record=True, width=200)
    session = TerminalSession(tmp_path / "index.sqlite3")
    folder = tmp_path / "My Notes"
    folder.mkdir()
    windows_path = str(folder / "chat.md").replace("/", "\\")

    _handle_command(console, session, f'/save "{windows_path}"')

    assert (folder / "chat.md").is_file()


def test_remember_keeps_text_verbatim(tmp_path, monkeypatch) -> None:
    session = TerminalSession(tmp_path / "index.sqlite3")
    monkeypatch.setattr(session.memory, "path", tmp_path / "kiki-memory.md")

    _handle_command(Console(record=True), session, r"/remember Use C:\work for scratch files")

    assert session.memory.notes() == [r"Use C:\work for scratch files"]


def test_answer_panels_are_titled_kiki() -> None:
    from kiki.terminal import render_outcome

    console = Console(record=True, width=80)
    render_outcome(console, ChatOutcome("Hello.", [], []), mode="chat", retrieval_mode="none")

    rendered = console.export_text()
    assert "Kiki · Chat" in rendered
