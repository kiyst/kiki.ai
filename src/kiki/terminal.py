from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from collections.abc import Callable
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
    WEB_SYSTEM_PROMPT,
    ChatOutcome,
    OllamaClient,
    ToolCallingAssistant,
    ToolTrace,
    resolve_citations,
    unsupported_sentences,
)
from .capabilities import Capability, route_prompt
from .diagnostics import build_diagnostics, diagnostics_markdown
from .finding import FileFinder, FindError, FindResult, format_size
from .folders_command import folders_command
from .input_editor import create_chat_input
from .memory import MemoryStore, SensitiveMemoryError
from .models import PROFILES, ModelRouter, ModelSelection
from .providers.weather import GEOCODING_URL, OpenMeteoWeatherProvider
from .personality import PRESETS, PersonaFile, PersonalitySettings, personality_prompt
from .rerank import build_reranker
from .retrieval import SearchResult, TextIndex
from .resilience import KikiError, safe_error
from .apply_command import apply_command
from .run_command import run_command
from .semantic import HybridRetriever, OllamaEmbeddingClient, SemanticIndex
from .settings import RetrievalSettings
from .self_knowledge import COMMAND_HELP, capabilities_text, self_knowledge_prompt
from .tools import ToolRegistry
from .web import PageSearch, WebError, WebPage, fetch_page, looks_like_url, offline_mode


INTERACTIVE_COMMANDS = (
    "/chat",
    "/rag",
    "/retry",
    "/copy",
    "/sources",
    "/find",
    "/folders",
    "/web",
    "/run",
    "/workspace",
    "/apply",
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
    "/persona",
    "/memory",
    "/remember",
    "/forget",
    "/model",
    "/diagnostics",
    "/capabilities",
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
        rerank: bool = True,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self.database = database
        self.model = model
        settings = settings or RetrievalSettings.from_environment()
        self.settings = settings if rerank else settings.with_overrides(reranker="none")
        self.model_profile = "auto"
        self.model_router = ModelRouter(model)
        self.last_model_selection = ModelSelection("fast", model, "session default")
        self.embedding_model = embedding_model
        self.weather = OpenMeteoWeatherProvider()
        self.mode = "chat"
        self.debug = False
        self.pending_weather_choices: list[dict[str, Any]] = []
        self.personality_path = database.resolve().parent / "kiki-personality.json"
        self.personality = PersonalitySettings.load(self.personality_path)
        self.persona = PersonaFile(database.resolve().parent / "kiki-persona.md")
        self.memory = MemoryStore(database.resolve().parent / "kiki-memory.md")
        self.histories: dict[str, list[dict[str, str]]] = {"chat": [], "rag": [], "web": []}
        self.last_prompts: dict[str, str | None] = {"chat": None, "rag": None, "web": None}
        self.last_outcomes: dict[str, ChatOutcome | None] = {"chat": None, "rag": None, "web": None}
        self.turns: list[dict[str, Any]] = []
        # Folder /apply may write into; chosen by the user each session, never saved.
        self.workspace: Path | None = None
        # Candidates from the last /find, kept for follow-ups by number.
        self.last_find: FindResult | None = None
        # The page from the last /web, kept so follow-up questions need no new download.
        self.web_page: WebPage | None = None
        self._set_index(database)

    @property
    def web_log(self) -> Path:
        return self.database.resolve().parent / "kiki-web-log.jsonl"

    def read_web_page(self, url: str) -> WebPage:
        page = fetch_page(url, log=self.web_log)
        if self.web_page is None or page.url != self.web_page.url:
            # Earlier turns were about another page; they would only mislead.
            self.histories["web"].clear()
        self.web_page = page
        return page

    def ask_web(self, command: str, question: str, *, overview: bool = False) -> ChatOutcome:
        """Answer from the current /web page, citing its passages like documents.

        Always recorded in the WEB conversation, which /web switches to."""
        assert self.web_page is not None
        self.mode = "web"
        self.last_model_selection = self.model_router.select(self.model_profile, Capability.RAG)
        search = PageSearch(self.web_page, overview=overview)
        system_prompt = self._system_prompt(WEB_SYSTEM_PROMPT)
        unmatched = [] if overview else search.unmatched_words(question)
        if unmatched:
            system_prompt += (
                "\n\nPage coverage note (from Kiki's code): no passage on this page contains most "
                f"of the question's words; these appear in none of the closest passages: "
                f"{', '.join(unmatched)}. The page probably does not answer this question. Answer "
                "only what the passages actually say, and if they do not answer it, begin with "
                "`Evidence is insufficient.`"
            )
        assistant = ToolCallingAssistant(
            OllamaClient(),
            ToolRegistry(search),
            model=self.last_model_selection.model,
            planner_model=self.model_router.models()["smart"],
            pre_retrieve=True,
            system_prompt=system_prompt,
            passages=self.settings.passages,
            max_evidence_characters=self.settings.context_characters,
            support_check=True,
        )
        outcome = assistant.ask(question, history=self.histories[self.mode])
        return self._remember(command, outcome, "page")[0]

    def _set_index(self, database: Path) -> None:
        self.index = TextIndex(database)
        self.database = self.index.database

    def set_database(self, database: Path) -> None:
        self._set_index(database)
        self.histories["rag"].clear()
        self.last_find = None

    def retrieval_backend(self) -> tuple[Any, str]:
        if self.index.embedding_count(self.embedding_model):
            semantic = SemanticIndex(
                self.index, OllamaEmbeddingClient(), self.embedding_model
            )
            backend = HybridRetriever(
                self.index,
                semantic,
                build_reranker(self.settings, self.model),
                candidates=self.settings.candidates,
                recovery=self.settings.recovery,
            )
            return backend, backend.mode
        return self.index, "lexical"

    def ask(self, prompt: str) -> tuple[ChatOutcome, str]:
        route = route_prompt(prompt, mode=self.mode)
        self.last_model_selection = self.model_router.select(
            self.model_profile, route.capability
        )
        if route.capability == Capability.MEMORY:
            memory_answer = self._handle_natural_memory(prompt)
            if memory_answer is not None:
                return self._remember(
                    prompt, ChatOutcome(memory_answer, [], []), "none"
                )
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
        if weather_location and offline_mode():
            self.pending_weather_choices.clear()
            return self._remember(
                prompt,
                ChatOutcome("Kiki is in offline mode (KIKI_OFFLINE is set), so she can't fetch "
                            "live weather.", [], []),
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
        if self.mode == "web":
            if self.web_page is None:
                return self._remember(prompt, ChatOutcome(
                    "No page is open. Type /web URL to read one, or /chat to go back to "
                    "ordinary conversation.", [], []), "none")
            return self.ask_web(prompt, prompt), "page"
        if self.mode == "rag":
            backend, retrieval_mode = self.retrieval_backend()
            registry = ToolRegistry(backend, weather=self.weather)
            assistant = ToolCallingAssistant(
                OllamaClient(),
                registry,
                model=self.last_model_selection.model,
                planner_model=self.model_router.models()["smart"],
                pre_retrieve=weather_location is None,
                system_prompt=self._system_prompt(RAG_SYSTEM_PROMPT),
                passages=self.settings.passages,
                max_evidence_characters=self.settings.context_characters,
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
                model=self.last_model_selection.model,
                pre_retrieve=False,
                system_prompt=self._system_prompt(CHAT_SYSTEM_PROMPT),
            )
        outcome = assistant.ask(prompt, history=self.histories[self.mode])
        if self.mode == "rag" and isinstance(backend, HybridRetriever):
            retrieval_mode = backend.mode
        return self._remember(prompt, outcome, retrieval_mode)

    def _system_prompt(self, base: str) -> str:
        sections = [
            base,
            personality_prompt(self.personality, self.persona.load()),
            self_knowledge_prompt(
                mode=self.mode, model_profile=self.model_profile
            ),
        ]
        memory = self.memory.prompt()
        if memory:
            sections.append(memory)
        return "\n\n".join(sections)

    def _handle_natural_memory(self, prompt: str) -> str | None:
        stripped = prompt.strip()
        remember = re.match(r"^(?:please\s+)?remember(?:\s+that)?\s+(.+)$", stripped, re.I)
        if remember:
            try:
                note = self.memory.remember(remember.group(1))
                return f"Remembered: {note}"
            except (SensitiveMemoryError, ValueError) as exc:
                return str(exc)
        forget = re.match(r"^(?:please\s+)?forget(?:\s+that)?\s+(.+)$", stripped, re.I)
        if forget:
            removed = self.memory.forget(forget.group(1))
            return (
                "Forgot: " + "; ".join(removed)
                if removed
                else "I couldn't find a matching saved memory."
            )
        if re.match(r"^what do you remember\b", stripped, re.I):
            notes = self.memory.numbered()
            return (
                "Saved memories:\n" + "\n".join(f"{number}. {note}" for number, note in notes)
                if notes
                else "I don't have any saved memories yet."
            )
        return None

    def diagnostics(self) -> dict[str, Any]:
        registry = ToolRegistry(self.index, weather=self.weather)
        return build_diagnostics(
            database=self.database,
            mode=self.mode,
            model_profile=self.model_profile,
            selected_model=self.last_model_selection.model,
            embedding_model=self.embedding_model,
            index_health=self.index.health(),
            tool_catalog=registry.catalog(),
            retrieval=self.settings.describe(self.model),
        )

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
            rerank_model = self.settings.resolved_rerank_model(self.model)
            if rerank_model and self.settings.reranker != "llama-cpp":
                ollama["rerank_model"] = (
                    f"{rerank_model} (installed)"
                    if rerank_model in installed
                    else f"{rerank_model} (missing: ollama pull {rerank_model})"
                )
        except Exception as exc:
            ollama = {"status": "unavailable", "error": str(exc)}
        try:
            if offline_mode():
                raise RuntimeError("offline mode (KIKI_OFFLINE is set); not checked")
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
        report = {
            "ollama": ollama,
            "index": self.index.health(),
            "weather": weather_status,
        }
        if self.settings.reranker == "llama-cpp":
            report["reranker"] = _rerank_server_health(self.settings.rerank_url)
        return report

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
            folder = self.database.parent / "saved-chats"
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
    rerank: bool = True,
    settings: RetrievalSettings | None = None,
) -> None:
    console = console or Console()
    session = TerminalSession(
        database,
        model=model,
        embedding_model=embedding_model,
        rerank=rerank,
        settings=settings,
    )
    _render_banner(console, session)
    editor = create_chat_input(
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
            status = {"rag": "Searching indexed evidence...",
                      "web": "Reading the passages that fit your question..."}
            with console.status(status.get(session.mode, "Thinking locally..."), spinner="dots"):
                outcome, retrieval_mode = session.ask(prompt)
            render_outcome(
                console,
                outcome,
                mode=session.mode,
                retrieval_mode=retrieval_mode,
                debug=session.debug,
            )
            if retrieval_mode == "page":
                _render_web_notes(console, outcome)
        except Exception as exc:  # terminal boundary: preserve session after provider/model errors
            error = exc.payload() if isinstance(exc, KikiError) else safe_error(exc)
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
    title = {"rag": "Kiki · RAG", "web": "Kiki · Web"}.get(mode, "Kiki · Chat")
    console.print(Panel(Markdown(outcome.answer or "_(No response)_"), title=title, border_style="cyan"))
    render_sources(console, outcome.sources, outcome.answer)
    if debug:
        render_trace(console, outcome, retrieval_mode)


def render_sources(
    console: Console, sources: list[dict[str, Any]], answer: str | None = None
) -> None:
    """Passages the answer cites, in citation order; uncited passages are counted.

    Without an answer every shown passage is listed, as before.
    """
    if not sources:
        return
    title = "Verified sources"
    listed = sources
    if answer is not None:
        cited = [item for item in resolve_citations(answer, sources) if item["resolved"]]
        if not cited:
            console.print(
                f"[dim]{len(sources)} passages were retrieved; the answer cites none.[/dim]"
            )
            return
        listed, title = cited, "Cited sources"
    table = Table(title=title, show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Document", style="bold")
    table.add_column("Location", no_wrap=True)
    for source in listed:
        table.add_row(
            str(source.get("passage_id") or source["source_id"]),
            _source_name(str(source["path"])),
            _citation_location(str(source.get("citation") or "")),
        )
    console.print(table)
    uncited = len(sources) - len(listed)
    if uncited:
        noun = "passage was" if uncited == 1 else "passages were"
        console.print(f"[dim]{uncited} more retrieved {noun} not cited. /sources all lists them.[/dim]")


def _source_name(path: str) -> str:
    # Web pages are cited by their full address so the user can open them.
    return path if path.startswith(("http://", "https://")) else Path(path).name


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


_CONFIDENCE_STYLES = {"Likely": "green", "Possible": "yellow", "Weak match": "dim", "Matches filters": "cyan"}


def render_find_results(console: Console, result: FindResult) -> None:
    if result.filters:
        console.print(f"[dim]Filters: {'; '.join(result.filters)}[/dim]")
    if not result.catalogued:
        console.print(Panel(
            "Nothing is catalogued yet. Index a folder first: kiki index FOLDER",
            border_style="yellow",
        ))
        return
    if not result.candidates:
        console.print(Panel("No file matches that description.", border_style="yellow"))
    for candidate in result.candidates:
        style = _CONFIDENCE_STYLES.get(candidate.confidence, "white")
        body = Text()
        body.append(f"{candidate.confidence}", style=f"bold {style}")
        if candidate.reasons:
            body.append(f" · {candidate.explanation}")
        body.append(f"\nFolder: {candidate.folder}  ·  Modified {candidate.modified}"
                    f"  ·  {format_size(candidate.size)}")
        if candidate.title:
            body.append(f"\nTitle: {candidate.title}")
        if not candidate.searchable:
            body.append("\nContents not readable by Kiki: found by name, folder, and type only.",
                        style="dim")
        if candidate.changed_since_indexing:
            body.append("\nChanged since it was indexed; run kiki index to refresh.", style="dim")
        heading = Text(f"{candidate.number}. {candidate.name}",
                       style=f"link {Path(candidate.path).as_uri()}")
        console.print(Panel(body, title=heading, title_align="left", border_style=style))
        # Plain line, never wrapped, so the path can be copied as-is.
        console.print(candidate.path, soft_wrap=True, markup=False, highlight=False)
    if result.missing_skipped:
        console.print(
            f"[yellow]{result.missing_skipped} indexed file(s) no longer exist and were skipped. "
            "Run kiki index on that folder to refresh.[/yellow]"
        )
    if len(result.candidates) > 1 and result.candidates[0].confidence != "Likely":
        console.print("[dim]Not sure which one? Narrow it with in:FOLDER, ext:pdf, "
                      "after:2025, or more words.[/dim]")


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
    console.print(Panel(text, title="Kiki", border_style="cyan"))


def _prompt_text(session: TerminalSession) -> str:
    color = {"rag": "magenta", "web": "green"}.get(session.mode, "cyan")
    debug = " · debug" if session.debug else ""
    return f"[{color}]{session.mode.upper()}{debug}[/{color}] [bold]you >[/bold] "


def _handle_command(
    console: Console, session: TerminalSession, command: str
) -> tuple[bool, str | None]:
    # Plain whitespace splitting: POSIX shlex treats backslashes as escapes and
    # would turn C:\Users\me\notes.md into C:Usersmenotes.md.
    parts = command.split()
    name = parts[0].casefold()
    rest = command.strip()[len(parts[0]) :].strip()
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
    if name == "/persona":
        action = parts[1].casefold() if len(parts) > 1 else "show"
        if action in {"show", "path"}:
            session.persona.ensure()
            console.print(
                Panel(
                    session.persona.load(),
                    title=f"Editable persona · {session.persona.path}",
                    border_style="cyan",
                )
            )
        elif action == "reset":
            backup = session.persona.reset()
            message = "Persona reset to Kiki's default."
            if backup:
                message += f" Previous text saved to {backup}."
            console.print(f"[green]{message}[/green]")
        else:
            console.print("[yellow]Usage: /persona [show|path|reset][/yellow]")
        return False, None
    if name in {"/memory", "/remember", "/forget"}:
        if name == "/memory":
            notes = session.memory.numbered()
            if notes:
                console.print(
                    Panel(
                        "\n".join(f"{number}. {note}" for number, note in notes),
                        title="Kiki memory · use /forget NUMBER",
                    )
                )
            else:
                console.print("[yellow]No saved memories.[/yellow]")
        elif not rest:
            console.print(f"[yellow]Usage: {name} TEXT[/yellow]")
        elif name == "/remember":
            try:
                note = session.memory.remember(rest)
                console.print(f"[green]Remembered:[/green] {note}")
            except (SensitiveMemoryError, ValueError) as exc:
                console.print(f"[yellow]{exc}[/yellow]")
        else:
            removed = session.memory.forget(rest)
            if removed:
                console.print("[green]Forgot:[/green] " + "; ".join(removed))
            else:
                console.print("[yellow]No matching memory found.[/yellow]")
        return False, None
    if name == "/model":
        if not rest:
            models = session.model_router.models()
            render_mapping(
                console,
                "Model profiles",
                {
                    "active_profile": session.model_profile,
                    "last_selected": session.last_model_selection.model,
                    **models,
                    "configuration": "KIKI_MODEL_FAST / SMART / MAX",
                },
            )
        elif rest.casefold() in PROFILES:
            session.model_profile = rest.casefold()
            console.print(f"[green]Model profile set to {session.model_profile.upper()}.[/green]")
        else:
            console.print(f"[yellow]Choose one of: {', '.join(PROFILES)}[/yellow]")
        return False, None
    if name == "/diagnostics":
        report = diagnostics_markdown(session.diagnostics())
        action = rest.casefold()
        if action == "copy":
            try:
                pyperclip.copy(report)
                console.print("[green]Copied privacy-filtered diagnostics.[/green]")
            except pyperclip.PyperclipException as exc:
                console.print(f"[red]Clipboard unavailable:[/red] {exc}")
        elif action == "save":
            path = session.database.parent / "kiki-diagnostics.md"
            path.write_text(report, encoding="utf-8")
            console.print(f"[green]Diagnostics saved to[/green] {path}")
        else:
            console.print(Markdown(report))
        return False, None
    if name == "/capabilities":
        console.print(Panel(Text(capabilities_text()), title="Kiki capabilities", border_style="cyan"))
        return False, None
    if name == "/retry":
        previous = session.prepare_retry()
        if previous is None:
            console.print("[yellow]There is no previous message to retry.[/yellow]")
            return False, None
        console.print("[dim]Regenerating the previous response…[/dim]")
        if previous.startswith("/web"):
            return _handle_command(console, session, previous)
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
            show_all = rest.casefold() == "all"
            render_sources(console, previous.sources, None if show_all else previous.answer)
        return False, None
    if name == "/find":
        if not rest:
            if session.last_find and session.last_find.candidates:
                render_find_results(console, session.last_find)
            else:
                console.print("[yellow]Usage: /find WORDS [ext:pdf] [in:FOLDER] [after:2025] "
                              "[before:2026-03] [larger:10MB][/yellow]")
            return False, None
        try:
            result = FileFinder(session.index).find(rest)
        except FindError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
            return False, None
        session.last_find = result
        render_find_results(console, result)
        return False, None
    if name == "/folders":
        if folders_command(
            console, session.index, rest, read=console.input,
            browse=lambda: _browse_path(console, Path.home(), purpose="folder",
                                        default_filename=None),
        ):
            session.last_find = None
        return False, None
    if name == "/web":
        _handle_web(console, session, command.strip(), rest)
        return False, None
    if name == "/run":
        previous = session.last_outcomes[session.mode]
        run_command(
            console,
            answer=previous.answer if previous else None,
            mode=session.mode,
            argument=_path_argument(rest) if rest else None,
        )
        return False, None
    if name == "/workspace":
        if not rest:
            console.print(
                f"Workspace: [cyan]{session.workspace}[/cyan]" if session.workspace else
                "No workspace chosen. [bold]/workspace PATH[/bold] or [bold]/workspace browse[/bold] "
                "picks the folder /apply may write into."
            )
            return False, None
        if rest.casefold() == "browse":
            selected = _browse_path(console, session.workspace or Path.home(),
                                    purpose="workspace", default_filename=None)
        else:
            selected = _path_argument(rest).expanduser()
        if selected is None:
            console.print("[dim]Workspace unchanged.[/dim]")
        elif not selected.is_dir():
            console.print(f"[yellow]Not a folder:[/yellow] {selected}")
        else:
            session.workspace = selected.resolve()
            console.print(f"Workspace set to [cyan]{session.workspace}[/cyan]. "
                          "/apply writes only inside it, after you approve a diff.")
        return False, None
    if name == "/apply":
        previous = session.last_outcomes[session.mode]
        apply_command(
            console,
            answer=previous.answer if previous else None,
            workspace=session.workspace,
            argument=_path_argument(rest) if rest else None,
            backups=session.database.resolve().parent / "kiki-backups",
        )
        return False, None
    if name == "/history":
        recent =[turn for turn in session.turns if turn["mode"] == session.mode][-10:]
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
        selected = _path_argument(rest) if rest else _browse_for_save(console, session)
        if selected is None:
            console.print("[dim]Save cancelled.[/dim]")
            return False, None
        path = session.export_transcript(selected)
        console.print(f"[green]Transcript saved to[/green] {path}")
        return False, None
    if name in {"/clear", "/new"}:
        session.clear_mode()
        console.print(f"Started a new {session.mode.upper()} conversation.")
        return False, None
    if name in {"/database", "/db"}:
        if not rest:
            console.print(
                f"Current database: [cyan]{session.database.resolve()}[/cyan]\n"
                "Use [bold]/database browse[/bold] to navigate or "
                "[bold]/database PATH[/bold] to set it directly."
            )
        elif rest.casefold() == "browse":
            selected = _browse_for_database(console, session.database.parent)
            if selected is None:
                console.print("[dim]Database selection cancelled.[/dim]")
                return False, None
            session.set_database(selected)
            console.print(f"RAG database changed to [cyan]{session.database.resolve()}[/cyan].")
        else:
            session.set_database(_path_argument(rest))
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
                "model_profile": session.model_profile,
                "last_model": session.last_model_selection.model,
                "model_reason": session.last_model_selection.reason,
                "embedding_model": session.embedding_model,
                "reranker": session.settings.reranker,
                "candidates / passages": (
                    f"{session.settings.candidates} / {session.settings.passages}"
                ),
                "memories": len(session.memory.notes()),
                "persona_file": session.persona.path,
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
        if offline_mode():
            console.print("[yellow]Kiki is in offline mode (KIKI_OFFLINE is set), "
                          "so she can't fetch live weather.[/yellow]")
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


_WEB_USAGE = ("Usage: /web URL [QUESTION] reads a page and switches to WEB mode, where plain "
              "messages ask about that page; /chat leaves; /web clear forgets the page.")


def _enter_web_mode(console: Console, session: TerminalSession) -> None:
    if session.mode != "web":
        session.mode = "web"
        console.print("[bold]Mode changed to WEB.[/bold] [dim]Your messages now ask about this page; "
                      "/chat goes back to conversation.[/dim]")


def _handle_web(console: Console, session: TerminalSession, command: str, rest: str) -> None:
    words = rest.split(maxsplit=1)
    if not words:
        if session.web_page:
            page = session.web_page
            console.print(f"Current page: [cyan]{page.title}[/cyan] · {page.url}")
            _enter_web_mode(console, session)
        console.print(f"[dim]{_WEB_USAGE}\nEvery request is logged in {session.web_log}.[/dim]")
        return
    if rest.casefold() == "clear":
        session.web_page = None
        session.histories["web"].clear()
        message = "Forgot the page. Nothing from it was saved."
        if session.mode == "web":
            session.mode = "chat"
            message += " Back to CHAT."
        console.print(f"[dim]{message}[/dim]")
        return
    overview = False
    if looks_like_url(words[0]):
        question = words[1].strip() if len(words) > 1 else ""
        console.print(f"[dim]Going online: fetching {words[0]}[/dim]")
        try:
            with console.status("Downloading the page...", spinner="dots"):
                page = session.read_web_page(words[0])
        except WebError as exc:
            console.print(f"[yellow]{exc}[/yellow]")
            return
        details = f"{page.words:,} words · {page.size / 1024:,.0f} KB from {page.host}"
        console.print(f"Read [cyan]{page.title}[/cyan] · {details}")
        if page.note:
            console.print(f"[dim]{page.note}[/dim]")
        if page.truncated:
            console.print("[yellow]The page was very large; only its first 5 MB were read.[/yellow]")
        if not question:
            question, overview = "Give a short overview of this page's main points.", True
    elif session.web_page is None:
        console.print(f"[yellow]No page yet. {_WEB_USAGE}[/yellow]")
        return
    else:
        question = rest
    _enter_web_mode(console, session)
    try:
        with console.status("Reading the passages that fit your question...", spinner="dots"):
            outcome = session.ask_web(command, question, overview=overview)
    except Exception as exc:  # terminal boundary: keep the session after model errors
        error = exc.payload() if isinstance(exc, KikiError) else safe_error(exc)
        console.print(Panel(f"{error['error']}\n\nCode: {error['code']} · Ref: {error['reference']}",
                            title="Request failed", border_style="red"))
        return
    render_outcome(console, outcome, mode="web", retrieval_mode="page", debug=session.debug)
    _render_web_notes(console, outcome)


def _render_web_notes(console: Console, outcome: ChatOutcome) -> None:
    """Flag unsupported sentences and say how much of the page was read."""
    flagged = unsupported_sentences(outcome.answer, outcome.sources)
    if flagged:
        examples = "\n".join(f"  • {_shorten(sentence, 110)}" for sentence in flagged[:3])
        more = f"\n  …and {len(flagged) - 3} more" if len(flagged) > 3 else ""
        console.print(Text(
            f"Check {'these' if len(flagged) > 1 else 'this'}: {len(flagged)} "
            f"{'sentences use' if len(flagged) > 1 else 'sentence uses'} details that aren't in the passages "
            f"Kiki read, so they may come from her general knowledge instead of the page:\n"
            f"{examples}{more}",
            style="yellow",
        ))
    shown = sum(len(str(source.get("evidence", ""))) for source in outcome.sources)
    count = len(outcome.sources)
    console.print(f"[dim]Kiki read {count} passage{'s' if count != 1 else ''} ({shown:,} characters) "
                  "picked from the page to fit her reading space.[/dim]")


def _shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _render_help(console: Console) -> None:
    table = Table(title="Interactive commands", show_lines=True)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Purpose")
    for command, purpose in COMMAND_HELP:
        table.add_row(Text(command), purpose)
    console.print(table)


def _browse_for_save(
    console: Console,
    session: TerminalSession,
    input_fn: Callable[[str], str] | None = None,
) -> Path | None:
    folder = session.database.parent / "saved-chats"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return _browse_path(
        console,
        folder,
        purpose="save",
        default_filename=f"kiki-{stamp}.md",
        input_fn=input_fn,
    )


def _browse_for_database(
    console: Console,
    start: Path,
    input_fn: Callable[[str], str] | None = None,
) -> Path | None:
    return _browse_path(
        console,
        start,
        purpose="database",
        default_filename=None,
        input_fn=input_fn,
    )


# Browser purposes that pick a folder, and what "here" does for each.
_FOLDER_PURPOSES = {
    "workspace": "use this folder as the workspace",
    "folder": "index this folder",
}


def _browse_path(
    console: Console,
    start: Path,
    *,
    purpose: str,
    default_filename: str | None,
    input_fn: Callable[[str], str] | None = None,
) -> Path | None:
    """Small terminal folder navigator used by save and database selection."""
    read = input_fn or console.input
    current = start.expanduser().resolve()
    while True:
        try:
            children = sorted(
                (item for item in current.iterdir() if item.is_dir()),
                key=lambda item: item.name.casefold(),
            )
            if purpose == "database":
                children.extend(
                    sorted(
                        (
                            item
                            for item in current.iterdir()
                            if item.is_file() and item.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}
                        ),
                        key=lambda item: item.name.casefold(),
                    )
                )
        except OSError as exc:
            console.print(f"[red]Cannot read that folder:[/red] {exc}")
            if current.parent == current:
                # An unreadable root has nowhere left to climb.
                return None
            current = current.parent
            continue

        table = Table(title=f"Kiki {purpose} browser · {current}")
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Name")
        table.add_column("Type", style="dim")
        for number, item in enumerate(children, start=1):
            table.add_row(str(number), item.name, "folder" if item.is_dir() else "database")
        if not children:
            table.add_row("—", "No matching items", "—")
        console.print(table)
        if purpose == "save":
            console.print(
                "[dim]number: open folder · here [NAME]: save here · new NAME: create/open folder · "
                "..: parent · path PATH: direct destination · cancel[/dim]"
            )
        elif purpose in _FOLDER_PURPOSES:
            console.print(
                f"[dim]number: open folder · here: {_FOLDER_PURPOSES[purpose]} · "
                "..: parent · path PATH: direct folder · cancel[/dim]"
            )
        else:
            console.print(
                "[dim]number: open folder/select database · ..: parent · "
                "path PATH: direct database · cancel[/dim]"
            )
        try:
            choice = read("Kiki browser > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        lowered = choice.casefold()
        if lowered == "cancel":
            return None
        if choice == "..":
            current = current.parent
            continue
        if lowered.startswith("path "):
            selected = Path(choice[5:].strip().strip('"')).expanduser().resolve()
            if purpose == "save":
                return selected / default_filename if selected.is_dir() else _markdown_path(selected)
            if purpose in _FOLDER_PURPOSES:
                if selected.is_dir():
                    return selected
                console.print("[yellow]Choose an existing folder.[/yellow]")
                continue
            if selected.is_file() and selected.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}:
                return selected
            console.print("[yellow]Choose an existing .sqlite, .sqlite3, or .db file.[/yellow]")
            continue
        if purpose in _FOLDER_PURPOSES and lowered == "here":
            return current
        if purpose == "save" and (lowered == "here" or lowered.startswith("here ")):
            filename = choice[4:].strip().strip('"') or str(default_filename)
            return current / _markdown_path(Path(filename)).name
        if purpose == "save" and lowered.startswith("new "):
            name = choice[4:].strip().strip('"')
            if not _safe_folder_name(name):
                console.print("[yellow]Use a single folder name without path separators.[/yellow]")
                continue
            created = current / name
            try:
                created.mkdir(exist_ok=False)
            except FileExistsError:
                if not created.is_dir():
                    console.print("[yellow]That name already belongs to a file.[/yellow]")
                    continue
            except OSError as exc:
                console.print(f"[red]Could not create folder:[/red] {exc}")
                continue
            current = created
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(children):
            selected = children[int(choice) - 1]
            if selected.is_dir():
                current = selected
            else:
                return selected
            continue
        console.print("[yellow]Unknown browser command.[/yellow]")


def _path_argument(text: str) -> Path:
    """A typed path, allowing surrounding quotes for paths that contain spaces."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return Path(text)


def _markdown_path(path: Path) -> Path:
    return path if path.suffix.casefold() == ".md" else path.with_suffix(".md")


def _safe_folder_name(name: str) -> bool:
    return bool(name) and name not in {".", ".."} and not any(
        character in name for character in '<>:"/\\|?*'
    )


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
    return f"{result.location_label} · source {result.source_id}"


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


def _rerank_server_health(url: str) -> dict[str, Any]:
    """Health of the local llama.cpp reranking server named in the settings."""
    try:
        health = httpx.get(f"{url.rstrip('/')}/health", timeout=2)
        health.raise_for_status()
        models = httpx.get(f"{url.rstrip('/')}/v1/models", timeout=2).json().get("data", [])
    except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
        return {
            "status": "unavailable",
            "url": url,
            "error": type(exc).__name__,
            "fix": "llama-server -m <reranker.gguf> --reranking --host 127.0.0.1 --port 8081",
        }
    return {
        "status": "ok",
        "url": url,
        "model": Path(str(models[0].get("id", ""))).name if models else "unknown",
    }
