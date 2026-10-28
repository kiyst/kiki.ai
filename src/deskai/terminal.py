from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

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
)
from .providers.weather import OpenMeteoWeatherProvider
from .retrieval import SearchResult, TextIndex
from .semantic import HybridRetriever, OllamaEmbeddingClient, SemanticIndex
from .tools import ToolRegistry


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
        self.histories: dict[str, list[dict[str, str]]] = {"chat": [], "rag": []}
        self._set_index(database)

    def _set_index(self, database: Path) -> None:
        self.database = database
        self.index = TextIndex(database)

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
        if self.mode == "rag":
            backend, retrieval_mode = self.retrieval_backend()
            registry = ToolRegistry(backend, weather=self.weather)
            assistant = ToolCallingAssistant(
                OllamaClient(),
                registry,
                model=self.model,
                pre_retrieve=True,
                system_prompt=RAG_SYSTEM_PROMPT,
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
                system_prompt=CHAT_SYSTEM_PROMPT,
            )
        history = self.histories[self.mode]
        outcome = assistant.ask(prompt, history=history)
        history.extend(
            [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": outcome.answer},
            ]
        )
        del history[:-12]
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

    while True:
        try:
            prompt = console.input(_prompt_text(session))
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
            console.print(Panel(str(exc), title="Request failed", border_style="red"))


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
    if outcome.sources:
        table = Table(title="Verified sources", show_lines=True)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Document", style="bold")
        table.add_column("Location", no_wrap=True)
        for source in outcome.sources:
            table.add_row(
                str(source["source_id"]),
                Path(str(source["path"])).name,
                _citation_location(str(source.get("citation") or "")),
            )
        console.print(table)
    if debug:
        render_trace(console, outcome, retrieval_mode)


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
        "Type [bold]/rag[/bold] or [bold]/chat[/bold] to switch, [bold]/help[/bold] for commands.\n\n"
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
    if name == "/clear":
        session.histories[session.mode].clear()
        console.print(f"Cleared {session.mode.upper()} conversation history.")
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
        ("/weather City, State", "Fetch a current Open-Meteo forecast directly."),
        ("/database PATH", "Change the SQLite index used by RAG mode."),
        ("/status", "Show active model, database, mode, and embedding count."),
        ("/debug", "Toggle validated tool traces."),
        ("/clear", "Clear history for the active mode."),
        ("/quit", "Close the terminal session."),
    )
    for command, purpose in rows:
        table.add_row(command, purpose)
    console.print(table)


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
