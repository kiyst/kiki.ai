from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .evals import load_cases, run_evaluation
from .model_client import RAG_SYSTEM_PROMPT, OllamaClient, ToolCallingAssistant
from .providers.weather import OpenMeteoWeatherProvider
from .retrieval import TextIndex
from .semantic import HybridRetriever, OllamaEmbeddingClient, SemanticIndex
from .terminal import (
    TerminalSession,
    render_mapping,
    render_outcome,
    render_search_results,
    render_weather,
    run_shell,
)
from .tools import ToolRegistry


DEFAULT_MODEL = "qwen3:4b-instruct"
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deskai",
        description="Local conversation, grounded document Q&A, and validated tools.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(".deskai/index.sqlite3"),
        help="SQLite document index (default: .deskai/index.sqlite3)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of formatted output",
    )
    commands = parser.add_subparsers(dest="command")

    shell = commands.add_parser("shell", help="Open the interactive chat/RAG terminal")
    _add_model_options(shell)

    chat = commands.add_parser(
        "chat", help="One ordinary conversational turn (no document search)"
    )
    chat.add_argument("prompt")
    _add_model_options(chat)
    chat.add_argument("--debug", action="store_true")

    rag = commands.add_parser(
        "rag", help="Ask an evidence-grounded question of indexed documents"
    )
    rag.add_argument("prompt")
    _add_model_options(rag)
    rag.add_argument("--lexical-only", action="store_true")
    rag.add_argument("--debug", action="store_true")

    index = commands.add_parser("index", help="Index or reconcile a selected folder")
    index.add_argument("root", type=Path)

    search = commands.add_parser("search", help="Search indexed files by exact terms")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)

    embed = commands.add_parser("embed", help="Generate missing local semantic vectors")
    embed.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    embed.add_argument("--batch-size", type=int, default=4)

    semantic = commands.add_parser(
        "semantic-search", help="Search indexed files by meaning"
    )
    semantic.add_argument("query")
    semantic.add_argument("--limit", type=int, default=5)
    semantic.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)

    hybrid = commands.add_parser(
        "hybrid-search", help="Fuse exact and semantic search rankings"
    )
    hybrid.add_argument("query")
    hybrid.add_argument("--limit", type=int, default=5)
    hybrid.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)

    weather = commands.add_parser("weather", help="Get current weather and a short forecast")
    weather.add_argument("location", help="City, State or postal code")
    weather.add_argument("--country", default="US", help="Two-letter country preference")
    weather.add_argument("--days", type=int, default=3, choices=range(1, 8))

    tool = commands.add_parser("tool", help="Invoke a validated tool directly")
    tool.add_argument("name", choices=("search_files", "get_weather"))
    tool.add_argument("arguments", help="JSON object")

    evaluate = commands.add_parser(
        "eval-rag", help="Run the fixed lexical/hybrid RAG evaluation"
    )
    evaluate.add_argument(
        "--cases", type=Path, default=Path("evals/history_cases.json")
    )
    evaluate.add_argument("--limit", type=int, default=5)
    evaluate.add_argument(
        "--split",
        choices=("all", "development", "holdout"),
        default="all",
    )
    evaluate.add_argument(
        "--with-model", action="store_true", help="Also run Qwen answers; slower"
    )
    evaluate.add_argument("--model", default=DEFAULT_MODEL)
    evaluate.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    evaluate.add_argument("--output", type=Path, help="Optional JSON receipt path")
    return parser


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)


def main() -> None:
    _configure_utf8_console()
    parser = _parser()
    arguments = parser.parse_args()
    console = Console()

    if arguments.command in (None, "shell"):
        if arguments.json:
            parser.error("--json is not available for the interactive shell")
        run_shell(
            arguments.database,
            model=getattr(arguments, "model", DEFAULT_MODEL),
            embedding_model=getattr(
                arguments, "embedding_model", DEFAULT_EMBEDDING_MODEL
            ),
            console=console,
        )
        return

    try:
        output, kind = _dispatch(arguments)
    except (OSError, RuntimeError, ValueError) as exc:
        if arguments.json:
            print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        else:
            console.print(Panel(str(exc), title="deskAI error", border_style="red"))
        raise SystemExit(1) from exc

    if arguments.json:
        print(json.dumps(_json_safe(output), indent=2, ensure_ascii=False))
    else:
        _render(console, kind, output, arguments)


def _dispatch(arguments: argparse.Namespace) -> tuple[Any, str]:
    index = TextIndex(arguments.database)
    if arguments.command == "index":
        return index.index_root(arguments.root), "mapping"
    if arguments.command == "search":
        return index.search(arguments.query, arguments.limit), "search"
    if arguments.command == "embed":
        semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.model)
        return semantic.embed_pending(arguments.batch_size), "mapping"
    if arguments.command in ("semantic-search", "hybrid-search"):
        semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.model)
        backend = (
            semantic
            if arguments.command == "semantic-search"
            else HybridRetriever(index, semantic)
        )
        return backend.search(arguments.query, arguments.limit), "search"
    if arguments.command == "weather":
        result = OpenMeteoWeatherProvider().get_weather(
            arguments.location, arguments.country, arguments.days
        )
        return result, "weather"
    if arguments.command == "tool":
        try:
            payload = json.loads(arguments.arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Tool arguments must be a JSON object")
        registry = ToolRegistry(index, weather=OpenMeteoWeatherProvider())
        return registry.call(arguments.name, payload), "mapping"
    if arguments.command in ("chat", "rag"):
        session = TerminalSession(
            arguments.database,
            model=arguments.model,
            embedding_model=arguments.embedding_model,
        )
        session.mode = arguments.command
        if arguments.command == "rag" and arguments.lexical_only:
            session.retrieval_backend = lambda: (session.index, "lexical")  # type: ignore[method-assign]
        outcome, retrieval_mode = session.ask(arguments.prompt)
        return {
            "answer": outcome.answer,
            "sources": outcome.sources,
            "tool_trace": [trace.__dict__ for trace in outcome.trace],
            "mode": arguments.command,
            "retrieval_mode": retrieval_mode,
            "_outcome": outcome,
        }, "outcome"
    if arguments.command == "eval-rag":
        return _run_eval(arguments, index), "evaluation"
    raise ValueError(f"Unknown command: {arguments.command}")


def _run_eval(arguments: argparse.Namespace, index: TextIndex) -> dict[str, Any]:
    cases = load_cases(arguments.cases)
    if arguments.split != "all":
        cases = [case for case in cases if case.split == arguments.split]
    if not cases:
        raise ValueError("No evaluation cases matched the selected split")
    if not index.embedding_count(arguments.embedding_model):
        raise ValueError("This database has no embeddings for the selected model")

    semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.embedding_model)
    hybrid = HybridRetriever(index, semantic)
    ask_model = None
    if arguments.with_model:
        assistant = ToolCallingAssistant(
            OllamaClient(),
            ToolRegistry(hybrid),
            model=arguments.model,
            pre_retrieve=True,
            system_prompt=RAG_SYSTEM_PROMPT,
        )
        ask_model = assistant.ask
    receipt = run_evaluation(
        cases, index, hybrid, limit=arguments.limit, ask_model=ask_model
    )
    receipt["configuration"] = {
        "database": str(arguments.database.resolve()),
        "cases": str(arguments.cases.resolve()),
        "split": arguments.split,
        "limit": arguments.limit,
        "embedding_model": arguments.embedding_model,
        "generation_model": arguments.model if arguments.with_model else None,
    }
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return receipt


def _json_safe(output: Any) -> Any:
    if isinstance(output, list) and (not output or hasattr(output[0], "to_dict")):
        return [item.to_dict() for item in output]
    if isinstance(output, dict) and "_outcome" in output:
        return {key: value for key, value in output.items() if key != "_outcome"}
    return output


def _render(
    console: Console, kind: str, output: Any, arguments: argparse.Namespace
) -> None:
    if kind == "search":
        render_search_results(console, output)
    elif kind == "weather":
        render_weather(console, output)
    elif kind == "outcome":
        render_outcome(
            console,
            output["_outcome"],
            mode=output["mode"],
            retrieval_mode=output["retrieval_mode"],
            debug=arguments.debug,
        )
    elif kind == "evaluation":
        _render_evaluation(console, output)
    else:
        render_mapping(
            console, arguments.command.replace("-", " ").title(), output
        )


def _render_evaluation(console: Console, receipt: dict[str, Any]) -> None:
    render_mapping(console, "RAG evaluation summary", receipt["summary"])
    table = Table(title="Cases", show_lines=True)
    table.add_column("Case")
    table.add_column("Split")
    table.add_column("Lexical")
    table.add_column("Hybrid")
    table.add_column("All expected")
    table.add_column("Model")
    for case in receipt["cases"]:
        table.add_row(
            case["id"],
            case["split"],
            _mark(case["lexical_any_hit"]),
            _mark(case["hybrid_any_hit"]),
            _mark(case["hybrid_all_hit"]),
            _mark(case.get("expected_model_source_hit")),
        )
    console.print(table)
    console.print(
        "[dim]Retrieval hits measure expected-source presence, not factual correctness. "
        "Model answers still require human support review.[/dim]"
    )


def _mark(value: bool | None) -> str:
    if value is None:
        return "N/A"
    return "[green]PASS[/green]" if value else "[red]MISS[/red]"


def _configure_utf8_console() -> None:
    """Keep source excerpts readable in legacy Windows terminal sessions."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    main()
