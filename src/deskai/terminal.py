from __future__ import annotations

import shlex
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pyperclip
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .model_client import (
    CHAT_SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT,
    ChatOutcome,
    OllamaClient,
    ToolCallingAssistant,
    ToolTrace,
)
from .input_editor import ChatInput
from .providers.weather import GEOCODING_URL, OpenMeteoWeatherProvider
from .personality import PRESETS, PersonalitySettings, personality_prompt
from .retrieval import SearchResult, TextIndex
from .resilience import DeskAIError, safe_error
from .semantic import HybridRetriever, OllamaEmbeddingClient, SemanticIndex
from .tools import ToolRegistry


INTERACTIVE_COMMANDS = (
    "/chat",
    "/rag",
    "/retry",
    "/copy",
    "/sources",
    "/history",
    "/save",
    "/new",
    "/clear",
    "/weather",
    "/database",
    "/status",
    "/doctor",
    "/debug",
    "/personality",
    "/help",
    "/exit",
)


class TerminalSession:
    def __init__(
        self,
        database: Path,
        *,
        model: str = "qwen3:4b-instruct",
        embedding_model: str = "qwen3-embedding:0.6b",
    ) -> None:
        self.database = database
        self.model = model
        self.embedding_model = embedding_model
        self.weather = OpenMeteoWeatherProvider()
        self.mode = "chat"
        self.debug = False
        self.pending_weather_choices: list[dict[str, Any]] = []
        self.personality_path = database.resolve().parent / "kiki-personality.json"
        self.personality = PersonalitySettings.load(self.personality_path)
        self.histories: dict[str, list[dict[str, str]]] = {"chat": [], "rag": []}
        self.last_prompts: dict[str, str | None] = {"chat": None, "rag": None}
        self.last_outcomes: dict[str, ChatOutcome | None] = {"chat": None, "rag": None}
        self.turns: list[dict[str, Any]] = []
        self._set_index(database)

    def _set_index(self, database: Path) -> None:
        self.index = TextIndex(database)
        self.database = self.index.database

    def set_database(self, database: Path) -> None:
        self._set_index(database)
        self.histories["rag"].clear()

    def retrieval_backend(self) -> tuple[Any, str]:
        if self.index.embedding_count(self.embedding_model):
            semantic = SemanticIndex(
                self.index, OllamaEmbeddingClient(), self.embedding_model
            )
            return HybridRetriever(self.index, semantic), "hybrid"
        return self.index, "lexical"

    def ask(self, prompt: str) -> tuple[ChatOutcome, str]:
        weather_location = _weather_location_from_prompt(prompt)
        if not weather_location and self.pending_weather_choices:
            if prompt.strip().casefold() in {"cancel", "never mind", "nevermind"}:
                self.pending_weather_choices.clear()
                return self._remember(
                    prompt,
                    ChatOutcome("Weather selection cancelled.", [], []),
                    "none",
                )
            selected = _select_weather_choice(prompt, self.pending_weather_choices)
            if selected:
                weather_location = _choice_query(selected)
            elif len(prompt.split()) <= 4:
                return self._remember(
                    prompt,
                    ChatOutcome(
                        "I still need one of the listed weather locations. "
                        "Reply with its number, state name, full label, or `cancel`.",
                        [],
                        [],
                    ),
                    "none",
                )
        if weather_location:
            registry = ToolRegistry(weather=self.weather, include_search=False)
            arguments = {"location": weather_location}
            result = registry.call("get_weather", arguments)
            outcome = ChatOutcome(
                answer=_weather_answer(result),
                trace=[
                    ToolTrace(
                        round=0,
                        name="get_weather",
                        arguments=arguments,
                        status=result["status"],
                    )
                ],
                sources=[],
            )
            data = result.get("data")
            self.pending_weather_choices = (
                list(data.get("choices", []))
                if isinstance(data, dict) and not data.get("resolved")
                else []
            )
            return self._remember(prompt, outcome, "none")
        if self.mode == "rag":
            backend, retrieval_mode = self.retrieval_backend()
            registry = ToolRegistry(backend, weather=self.weather)
            assistant = ToolCallingAssistant(
                OllamaClient(),
                registry,
                model=self.model,
                pre_retrieve=weather_location is None,
                system_prompt=f"{RAG_SYSTEM_PROMPT}\n\n{personality_prompt(self.personality)}",
            )
        else:
            retrieval_mode = "none"
            registry = ToolRegistry(
                weather=self.weather,
                include_search=False,
            )
            assistant = ToolCallingAssistant(
                OllamaClient(),
                registry,
                model=self.model,
                pre_retrieve=False,
                system_prompt=f"{CHAT_SYSTEM_PROMPT}\n\n{personality_prompt(self.personality)}",
            )
        outcome = assistant.ask(prompt, history=self.histories[self.mode])
        if self.mode == "rag" and isinstance(backend, HybridRetriever):
            if backend.last_fallback_reason:
                retrieval_mode = "lexical fallback (embedding service unavailable)"
        return self._remember(prompt, outcome, retrieval_mode)

    def doctor(self) -> dict[str, Any]:
        try:
            response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
            response.raise_for_status()
            payload = response.json()
            installed = {
                str(item.get("name"))
                for item in payload.get("models", [])
                if isinstance(item, dict)
            }
            ollama: dict[str, Any] = {
                "status": "ok",
                "generation_model": "installed" if self.model in installed else "missing",
                "embedding_model": "installed" if self.embedding_model in installed else "missing",
            }
        except Exception as exc:
            ollama = {"status": "unavailable", "error": str(exc)}
        try:
            weather_response = httpx.get(
                GEOCODING_URL,
                params={"name": "Boston", "count": 1, "format": "json"},
                timeout=3,
            )
            weather_response.raise_for_status()
            weather_status: dict[str, Any] = {
                "status": "ok",
                "http_status": weather_response.status_code,
            }
        except Exception as exc:
            weather_status = {"status": "unavailable", "error": str(exc)}
        weather_status.update(
            {
                "circuit": self.weather.circuit_breaker.state,
                "cached_locations": len(self.weather._cache),
            }
        )
        return {
            "ollama": ollama,
            "index": self.index.health(),
            "weather": weather_status,
        }

    def clear_mode(self) -> None:
        self.histories[self.mode].clear()
        self.last_prompts[self.mode] = None
        self.last_outcomes[self.mode] = None
        self.pending_weather_choices.clear()
        self.turns = [turn for turn in self.turns if turn["mode"] != self.mode]

    def prepare_retry(self) -> str | None:
        prompt = self.last_prompts[self.mode]
        if prompt is None:
            return None
        history = self.histories[self.mode]
        if len(history) >= 2 and history[-2].get("content") == prompt:
            del history[-2:]
        for index in range(len(self.turns) - 1, -1, -1):
            if self.turns[index]["mode"] == self.mode:
                del self.turns[index]
                break
        self.last_prompts[self.mode] = None
        self.last_outcomes[self.mode] = None
        return prompt

    def export_transcript(self, path: Path | None = None) -> Path:
        if path is None:
            folder = self.database.parent / "transcripts"
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = folder / f"kiki-{stamp}.md"
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Kiki transcript", ""]
        for turn in self.turns:
            lines.extend(
                [
                    f"## {str(turn['mode']).upper()} · You",
                    "",
                    str(turn["prompt"]),
                    "",
                    "## Kiki",
                    "",
                    str(turn["answer"]),
                    "",
                ]
            )
            sources = turn.get("sources") or []
            if sources:
                lines.append("Sources:")
                lines.extend(f"- {source.get('citation')}" for source in sources)
                lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _remember(
        self, prompt: str, outcome: ChatOutcome, retrieval_mode: str
    ) -> tuple[ChatOutcome, str]:
        history = self.histories[self.mode]
        history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": outcome.answer},
            ]
        )
        del history[:-12]
        self.last_prompts[self.mode] = prompt
        self.last_outcomes[self.mode] = outcome
        self.turns.append(
            {
                "mode": self.mode,
                "prompt": prompt,
                "answer": outcome.answer,
                "sources": outcome.sources,
            }
        )
        return outcome, retrieval_mode


def run_shell(
    database: Path,
    *,
    model: str = "qwen3:4b-instruct",
    embedding_model: str = "qwen3-embedding:0.6b",
    console: Console | None = None,
) -> None:
    console = console or Console()
    session = TerminalSession(
        database, model=model, embedding_model=embedding_model
    )
    _render_banner(console, session)
    editor = ChatInput(
        history_path=session.database.parent / "kiki-input-history",
        commands=INTERACTIVE_COMMANDS,
    )

    while True:
        try:
            prompt = editor.prompt(session.mode, session.debug)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Session closed.[/dim]")
            return
        prompt = prompt.strip()
        if not prompt:
            continue
        if prompt.startswith("/"):
            should_exit, immediate_prompt = _handle_command(console, session, prompt)
            if should_exit:
                return
            if immediate_prompt is None:
                continue
            prompt = immediate_prompt
        try:
            with console.status(
                "Searching indexed evidence..." if session.mode == "rag" else "Thinking locally...",
                spinner="dots",
            ):
                outcome, retrieval_mode = session.ask(prompt)
            render_outcome(
                console,
                outcome,
                mode=session.mode,
                retrieval_mode=retrieval_mode,
                debug=session.debug,
            )
        except Exception as exc:  # terminal boundary: preserve session after provider/model errors
            error = exc.payload() if isinstance(exc, DeskAIError) else safe_error(exc)
            message = f"{error['error']}\n\nCode: {error['code']} · Ref: {error['reference']}"
            console.print(Panel(message, title="Request failed", border_style="red"))


def render_outcome(
    console: Console,
    outcome: ChatOutcome,
    *,
    mode: str,
    retrieval_mode: str,
    debug: bool = False,
) -> None:
    title = "deskAI · RAG" if mode == "rag" else "deskAI · Chat"
    console.print(Panel(Markdown(outcome.answer or "_(No response)_"), title=title, border_style="cyan"))
    render_sources(console, outcome.sources)
    if debug:
        render_trace(console, outcome, retrieval_mode)


def render_sources(console: Console, sources: list[dict[str, Any]]) -> None:
    if not sources:
        return
    table = Table(title="Verified sources", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Document", style="bold")
    table.add_column("Location", no_wrap=True)
    for source in sources:
        table.add_row(
            str(source["source_id"]),
            Path(str(source["path"])).name,
            _citation_location(str(source.get("citation") or "")),
        )
    console.print(table)


def render_trace(console: Console, outcome: ChatOutcome, retrieval_mode: str) -> None:
    table = Table(title=f"Tool trace · retrieval: {retrieval_mode}")
    table.add_column("Round", justify="right")
    table.add_column("Tool")
    table.add_column("Arguments")
    table.add_column("Status")
    for trace in outcome.trace:
        table.add_row(
            str(trace.round),
            trace.name,
            ", ".join(f"{key}={value!r}" for key, value in trace.arguments.items()),
            trace.status,
        )
    if not outcome.trace:
        table.add_row("—", "none", "—", "—")
    console.print(table)


def render_search_results(console: Console, results: list[SearchResult]) -> None:
    if not results:
        console.print(Panel("No matching indexed passages.", border_style="yellow"))
        return
    for rank, result in enumerate(results, start=1):
        heading = f"{rank}. {Path(result.path).name} · {_result_location(result)}"
        console.print(Panel(result.excerpt, title=heading, border_style="blue"))


def render_weather(console: Console, result: dict[str, Any]) -> None:
    if not result.get("resolved"):
        table = Table(title="Location needs clarification")
        table.add_column("Choice")
        table.add_column("Timezone")
        for choice in result.get("choices", []):
            table.add_row(str(choice.get("label")), str(choice.get("timezone", "")))
        console.print(Panel(str(result.get("message", "Location not resolved")), border_style="yellow"))
        if result.get("choices"):
            console.print(table)
        return

    current = result["current"]
    location = result["location"]["label"]
    summary = Text()
    summary.append(f"{current['condition']}\n", style="bold")
    summary.append(
        f"{current['temperature_f']} °F / {current['temperature_c']} °C"
        f"  ·  feels like {current['feels_like_f']} °F / {current['feels_like_c']} °C\n"
    )
    summary.append(
        f"Humidity {current['relative_humidity_percent']}%  ·  "
        f"Wind {current['wind_kmh']} km/h  ·  Precipitation {current['precipitation_mm']} mm"
    )
    console.print(Panel(summary, title=f"Weather · {location}", border_style="green"))
    table = Table(title=f"Forecast · {result.get('timezone')}")
    table.add_column("Date")
    table.add_column("Conditions")
    table.add_column("High")
    table.add_column("Low")
    table.add_column("Precip.")
    for day in result["daily"]:
        table.add_row(
            str(day["date"]),
            str(day["condition"]),
            f"{day['high_f']} °F / {day['high_c']} °C",
            f"{day['low_f']} °F / {day['low_c']} °C",
            f"{day['precipitation_probability_percent']}% · {day['precipitation_mm']} mm",
        )
    console.print(table)
    console.print(f"[dim]{result['attribution']} Retrieved {result['retrieved_at']}.[/dim]")


def render_mapping(console: Console, title: str, payload: dict[str, Any]) -> None:
    table = Table(title=title)
    table.add_column("Field", style="cyan")
    table.add_column("Value", overflow="fold")
    for key, value in payload.items():
        table.add_row(key.replace("_", " ").title(), str(value))
    console.print(table)


def _render_banner(console: Console, session: TerminalSession) -> None:
    text = (
        "[bold]Local assistant[/bold]\n"
        "[cyan]CHAT[/cyan] is ordinary conversation. [magenta]RAG[/magenta] answers from indexed evidence.\n"
        "Type [bold]/rag[/bold] or [bold]/chat[/bold] to switch; press [bold]Tab[/bold] for commands.\n"
        "Use [bold]/help[/bold] for shortcuts and [bold]/new[/bold] for a fresh conversation.\n\n"
        f"Database: [dim]{session.database.resolve()}[/dim]"
    )
    console.print(Panel(text, title="deskAI", border_style="cyan"))


def _prompt_text(session: TerminalSession) -> str:
    color = "magenta" if session.mode == "rag" else "cyan"
    debug = " · debug" if session.debug else ""
    return f"[{color}]{session.mode.upper()}{debug}[/{color}] [bold]you >[/bold] "


def _handle_command(
    console: Console, session: TerminalSession, command: str
) -> tuple[bool, str | None]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        console.print(f"[red]Invalid command:[/red] {exc}")
        return False, None
    name = parts[0].casefold()
    rest = " ".join(parts[1:]).strip()
    if name in {"/quit", "/exit"}:
        console.print("[dim]Session closed.[/dim]")
        return True, None
    if name in {"/chat", "/rag"}:
        session.mode = name[1:]
        console.print(f"[bold]Mode changed to {session.mode.upper()}.[/bold]")
        return False, rest or None
    if name == "/debug":
        session.debug = not session.debug
        console.print(f"Debug trace {'enabled' if session.debug else 'disabled'}.")
        return False, None
    if name == "/personality":
        _handle_personality(console, session, parts[1:])
        return False, None
    if name == "/retry":
        previous = session.prepare_retry()
        if previous is None:
            console.print("[yellow]There is no previous message to retry.[/yellow]")
            return False, None
        console.print("[dim]Regenerating the previous response…[/dim]")
        return False, previous
    if name == "/copy":
        previous = session.last_outcomes[session.mode]
        if previous is None:
            console.print("[yellow]There is no response to copy.[/yellow]")
            return False, None
        try:
            pyperclip.copy(previous.answer)
            console.print("[green]Copied the last response.[/green]")
        except pyperclip.PyperclipException as exc:
            console.print(f"[red]Clipboard unavailable:[/red] {exc}")
        return False, None
    if name == "/sources":
        previous = session.last_outcomes[session.mode]
        if previous is None or not previous.sources:
            console.print("[yellow]The last response has no verified sources.[/yellow]")
        else:
            render_sources(console, previous.sources)
        return False, None
    if name == "/history":
        recent = [turn for turn in session.turns if turn["mode"] == session.mode][-10:]
        if not recent:
            console.print("[yellow]This conversation has no messages yet.[/yellow]")
            return False, None
        table = Table(title=f"Recent {session.mode.upper()} prompts")
        table.add_column("#", justify="right", style="dim")
        table.add_column("Prompt", overflow="fold")
        for number, turn in enumerate(recent, start=1):
            table.add_row(str(number), str(turn["prompt"]))
        console.print(table)
        return False, None
    if name == "/save":
        path = session.export_transcript(Path(rest) if rest else None)
        console.print(f"[green]Transcript saved to[/green] {path}")
        return False, None
    if name in {"/clear", "/new"}:
        session.clear_mode()
        console.print(f"Started a new {session.mode.upper()} conversation.")
        return False, None
    if name in {"/database", "/db"}:
        if not rest:
            console.print(f"Current database: [cyan]{session.database.resolve()}[/cyan]")
        else:
            session.set_database(Path(rest))
            console.print(f"RAG database changed to [cyan]{session.database.resolve()}[/cyan].")
        return False, None
    if name == "/status":
        render_mapping(
            console,
            "Session status",
            {
                "mode": session.mode,
                "database": session.database.resolve(),
                "embeddings": session.index.embedding_count(session.embedding_model),
                "model": session.model,
                "embedding_model": session.embedding_model,
                "debug": session.debug,
            },
        )
        return False, None
    if name == "/doctor":
        report = session.doctor()
        for component, details in report.items():
            render_mapping(console, f"Health · {component}", details)
        return False, None
    if name == "/weather":
        if not rest:
            console.print("[yellow]Usage: /weather City, State[/yellow]")
            return False, None
        try:
            with console.status("Contacting Open-Meteo...", spinner="dots"):
                result = session.weather.get_weather(rest)
            render_weather(console, result)
        except Exception as exc:
            console.print(Panel(str(exc), title="Weather failed", border_style="red"))
        return False, None
    if name == "/help":
        _render_help(console)
        return False, None
    console.print(f"[yellow]Unknown command {parts[0]}.[/yellow] Type /help.")
    return False, None


def _render_help(console: Console) -> None:
    table = Table(title="Interactive commands", show_lines=True)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Purpose")
    rows = (
        ("/chat [message]", "Switch to ordinary local conversation."),
        ("/rag [question]", "Switch to evidence-grounded document Q&A."),
        ("/retry", "Regenerate the last response."),
        ("/copy", "Copy the last response to the system clipboard."),
        ("/sources", "Show the last response's verified RAG sources again."),
        ("/history", "Show the last ten prompts in this conversation."),
        ("/save [PATH]", "Export this session to a Markdown transcript."),
        ("/new", "Start a fresh conversation in the active mode."),
        ("/weather City, State", "Fetch a current Open-Meteo forecast directly."),
        ("/database PATH", "Change the SQLite index used by RAG mode."),
        ("/status", "Show active model, database, mode, and embedding count."),
        ("/doctor", "Check Ollama models, index integrity, and provider health."),
        ("/debug", "Toggle validated tool traces."),
        ("/personality", "Show or adjust warmth, wit, opinions, and verbosity."),
        ("/clear", "Alias for /new."),
        ("/quit", "Close the terminal session."),
    )
    for command, purpose in rows:
        table.add_row(command, purpose)
    console.print(table)


def _handle_personality(
    console: Console, session: TerminalSession, arguments: list[str]
) -> None:
    if not arguments:
        render_mapping(
            console,
            "Kiki personality · 0 restrained, 3 strongest",
            {
                **session.personality.__dict__,
                "presets": ", ".join(PRESETS),
                "usage": "/personality wit 3 · /personality preset lively",
            },
        )
        return
    if len(arguments) == 2 and arguments[0].casefold() == "preset":
        preset = arguments[1].casefold()
        selected = PRESETS.get(preset)
        if selected is None:
            console.print(f"[yellow]Unknown preset.[/yellow] Choose: {', '.join(PRESETS)}")
            return
        session.personality = PersonalitySettings(**selected.__dict__)
    elif len(arguments) == 2 and arguments[0].casefold() in session.personality.__dict__:
        try:
            value = int(arguments[1])
        except ValueError:
            value = -1
        if not 0 <= value <= 3:
            console.print("[yellow]Personality levels must be integers from 0 to 3.[/yellow]")
            return
        setattr(session.personality, arguments[0].casefold(), value)
    else:
        console.print(
            "[yellow]Usage: /personality, /personality preset lively, or "
            "/personality wit 0-3[/yellow]"
        )
        return
    session.personality.save(session.personality_path)
    console.print("[bold]Personality updated and saved.[/bold]")


def _result_location(result: SearchResult) -> str:
    label = "page" if result.location_kind == "page" else "lines"
    span = str(result.start_location)
    if result.end_location != result.start_location:
        span += f"-{result.end_location}"
    return f"{label} {span} · source {result.source_id}"


def _citation_location(citation: str) -> str:
    if "(" in citation and citation.endswith(")"):
        return citation.rsplit("(", 1)[1][:-1]
    return "see JSON/debug output"


def _weather_location_from_prompt(prompt: str) -> str | None:
    match = re.search(
        r"\b(?:weather|forecast|temperature)\s+(?:in|of|for|at)\s+(.+)$",
        prompt.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    location = re.sub(r"\s+please\s*$", "", match.group(1), flags=re.IGNORECASE)
    return location.strip(" \t.,?!") or None


def _weather_answer(result: dict[str, Any]) -> str:
    if result.get("status") != "ok":
        return f"Weather lookup failed: {result.get('error', 'unknown provider error')}"
    data = result.get("data")
    if not isinstance(data, dict):
        return "Weather lookup failed: the provider returned an invalid response."
    if not data.get("resolved"):
        lines = [str(data.get("message", "The location could not be resolved."))]
        choices = data.get("choices") or []
        if choices:
            lines.append("\nPossible matches:")
            lines.extend(
                f"{number}. {choice.get('label')}"
                for number, choice in enumerate(choices[:5], start=1)
            )
        return "\n".join(lines)

    current = data["current"]
    label = data["location"]["label"]
    lines = [
        f"**{label}:** {current['condition']}, "
        f"{current['temperature_f']} °F / {current['temperature_c']} °C "
        f"(feels like {current['feels_like_f']} °F / {current['feels_like_c']} °C).",
        f"Humidity {current['relative_humidity_percent']}%; wind {current['wind_kmh']} km/h; "
        f"precipitation {current['precipitation_mm']} mm.",
        "\n**Forecast:**",
    ]
    if data.get("stale"):
        lines.insert(0, f"⚠️ {data.get('warning', 'Showing cached weather data.')}\n")
    for day in data.get("daily", []):
        lines.append(
            f"- {day['date']}: {day['condition']}; high {day['high_f']} °F / "
            f"{day['high_c']} °C, low {day['low_f']} °F / {day['low_c']} °C; "
            f"precipitation chance {day['precipitation_probability_percent']}%."
        )
    lines.append(
        f"\n_{data.get('attribution', 'Weather data by Open-Meteo.')} "
        f"Retrieved {data.get('retrieved_at', 'just now')}._"
    )
    return "\n".join(lines)


def _select_weather_choice(
    response: str, choices: list[dict[str, Any]]
) -> dict[str, Any] | None:
    requested = response.strip().casefold().strip(" .?!")
    ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
    if requested.isdigit():
        position = int(requested)
        return choices[position - 1] if 1 <= position <= len(choices) else None
    if requested in ordinals:
        position = ordinals[requested]
        return choices[position - 1] if position <= len(choices) else None

    matches: list[dict[str, Any]] = []
    for choice in choices:
        label = str(choice.get("label", ""))
        components = {part.strip().casefold() for part in label.split(",")}
        if requested == label.casefold() or requested in components:
            matches.append(choice)
    return matches[0] if len(matches) == 1 else None


def _choice_query(choice: dict[str, Any]) -> str:
    parts = [part.strip() for part in str(choice.get("label", "")).split(",")]
    return ", ".join(parts[:2])
