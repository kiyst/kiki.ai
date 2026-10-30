from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .behavior_evals import load_behavior_cases, run_behavior_evaluation
from .coding_evals import load_coding_cases, run_coding_evaluation
from .evals import load_cases, run_evaluation
from .finding import FileFinder
from .model_client import (
    CHAT_SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT,
    OllamaClient,
    ToolCallingAssistant,
)
from .providers.weather import OpenMeteoWeatherProvider
from .personality import PersonalitySettings, personality_prompt
from .rerank import build_reranker
from .retrieval import TextIndex
from .retrieval_evals import (
    GpuMemorySampler,
    evaluation_environment,
    load_retrieval_cases,
    run_retrieval_evaluation,
)
from .resilience import KikiError, safe_error
from .semantic import HybridRetriever, OllamaEmbeddingClient, SemanticIndex
from .settings import RERANKERS, RetrievalSettings
from .terminal import (
    TerminalSession,
    render_mapping,
    render_find_results,
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
        prog="kiki",
        description="Local conversation, grounded document Q&A, and validated tools.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(".kiki/index.sqlite3"),
        help="SQLite document index (default: .kiki/index.sqlite3)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of formatted output",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Skip reranking of RAG candidates (same as --reranker none)",
    )
    retrieval = parser.add_argument_group(
        "retrieval settings", "Override KIKI_RAG_* environment settings for this run"
    )
    retrieval.add_argument("--reranker", choices=RERANKERS)
    retrieval.add_argument("--rerank-url", help="Local llama.cpp reranking server (llama-cpp)")
    retrieval.add_argument("--rerank-model", help="Model used by the selected reranker")
    retrieval.add_argument("--candidates", type=int, help="First-stage pool size (default 20)")
    retrieval.add_argument("--passages", type=int, help="Passages given to the answer model (default 5)")
    retrieval.add_argument("--rerank-batch-size", type=int, help="Concurrent reranker requests")
    retrieval.add_argument("--rerank-timeout", type=float, help="Seconds per reranker request")
    retrieval.add_argument(
        "--context-characters", type=int, help="Evidence characters shown to the answer model"
    )
    retrieval.add_argument(
        "--recovery",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="One bounded rewritten-query retry when reranked evidence is weak",
    )
    commands = parser.add_subparsers(dest="command")

    shell = commands.add_parser("shell", help="Open the interactive chat/RAG terminal")
    _add_model_options(shell)

    run = commands.add_parser("run", help="Open the interactive assistant (friendly alias)")
    _add_model_options(run)

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

    find = commands.add_parser(
        "find", help="Find whole files by name, folder, type, title, or contents"
    )
    find.add_argument("query", help="Words plus optional filters such as ext:pdf in:Taxes after:2025")
    find.add_argument("--limit", type=int, default=3)

    find_eval = commands.add_parser(
        "eval-find", help="Score /find on generated folders (development or holdout seeds)"
    )
    find_eval.add_argument("--split", choices=("development", "holdout"), default="development")
    find_eval.add_argument("--output", type=Path, help="Optional JSON receipt path")

    web_eval = commands.add_parser(
        "eval-web", help="Score /web answers on live pages (goes online; uses the local model)"
    )
    web_eval.add_argument("--cases", type=Path,
                          help="Default: evals/web_cases.json, or evals/web_adversarial_cases.json "
                               "for --split adversarial")
    web_eval.add_argument("--split", choices=("development", "holdout", "adversarial",
                                              "adversarial-holdout", "adversarial-holdout-2",
                                              "adversarial-holdout-3", "all"),
                          default="development",
                          help="adversarial: attack pages served from memory, nothing goes online")
    web_eval.add_argument("--runs", type=int, default=1, help="Times to ask each question")
    web_eval.add_argument("--output", type=Path, help="Optional JSON receipt path")

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

    commands.add_parser(
        "doctor", help="Check Ollama models, index integrity, and provider readiness"
    )

    sandbox = commands.add_parser(
        "sandbox", help="Set up or check the Python code sandbox (WebAssembly)"
    )
    sandbox.add_argument(
        "action",
        choices=("setup", "doctor"),
        help="setup: download (about 14 MB), verify, and prepare the pinned runtime; "
        "doctor: check it and run a test program",
    )

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

    retrieval_eval = commands.add_parser(
        "eval-retrieval",
        help="Score passage-level retrieval separately from answer generation",
    )
    retrieval_eval.add_argument(
        "--cases", type=Path, default=Path("evals/retrieval_cases.json")
    )
    retrieval_eval.add_argument(
        "--limit", type=int, default=None, help="Top-k scored (default: configured passages)"
    )
    retrieval_eval.add_argument(
        "--split", choices=("all", "development", "holdout"), default="all"
    )
    retrieval_eval.add_argument(
        "--methods",
        default="lexical,hybrid,rerank",
        help=(
            "Comma-separated subset of lexical, hybrid, rerank (configured reranker), "
            "grader, llama-cpp, qwen3-reranker"
        ),
    )
    retrieval_eval.add_argument("--model", default=DEFAULT_MODEL)
    retrieval_eval.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    retrieval_eval.add_argument("--output", type=Path, help="Optional JSON receipt path")

    coding = commands.add_parser(
        "eval-chat", help="Run live medium/hard coding refusal and concept regressions"
    )
    coding.add_argument(
        "--cases", type=Path, default=Path("evals/coding_cases.json")
    )
    coding.add_argument("--model", default=DEFAULT_MODEL)
    coding.add_argument(
        "--case", action="append", dest="case_ids", help="Run a named case (repeatable)"
    )
    coding.add_argument("--limit", type=int, default=0, help="Run only the first N cases")
    coding.add_argument("--output", type=Path, help="Optional JSON receipt path")

    behavior = commands.add_parser(
        "eval-behavior",
        help="Run benign refusal, relevance, and persona-leak regressions",
    )
    behavior.add_argument(
        "--cases", type=Path, default=Path("evals/behavior_cases.json")
    )
    behavior.add_argument("--model", default=DEFAULT_MODEL)
    behavior.add_argument(
        "--case", action="append", dest="case_ids", help="Run a named case (repeatable)"
    )
    behavior.add_argument("--limit", type=int, default=0, help="Run only the first N cases")
    behavior.add_argument("--output", type=Path, help="Optional JSON receipt path")
    return parser


def _add_model_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)


def main() -> None:
    _configure_utf8_console()
    parser = _parser()
    arguments = parser.parse_args()
    console = Console()

    if arguments.command in (None, "shell", "run"):
        if arguments.json:
            parser.error("--json is not available for the interactive shell")
        try:
            settings = _retrieval_settings(arguments)
        except ValueError as exc:
            parser.error(str(exc))
        run_shell(
            arguments.database,
            model=getattr(arguments, "model", DEFAULT_MODEL),
            embedding_model=getattr(
                arguments, "embedding_model", DEFAULT_EMBEDDING_MODEL
            ),
            console=console,
            settings=settings,
        )
        return

    try:
        output, kind = _dispatch(arguments)
    except Exception as exc:
        error = exc.payload() if isinstance(exc, KikiError) else safe_error(exc)
        if arguments.json:
            print(json.dumps(error, indent=2))
        else:
            console.print(
                Panel(
                    f"{error['error']}\n\nCode: {error['code']} · Ref: {error['reference']}",
                    title="Kiki error",
                    border_style="red",
                )
            )
        raise SystemExit(1) from exc

    if arguments.json:
        print(json.dumps(_json_safe(output), indent=2, ensure_ascii=False))
    else:
        _render(console, kind, output, arguments)


def _retrieval_settings(arguments: argparse.Namespace) -> RetrievalSettings:
    settings = RetrievalSettings.from_environment().with_overrides(
        reranker=arguments.reranker,
        rerank_model=arguments.rerank_model,
        candidates=arguments.candidates,
        passages=arguments.passages,
        rerank_batch_size=arguments.rerank_batch_size,
        rerank_timeout=arguments.rerank_timeout,
        context_characters=arguments.context_characters,
        recovery=arguments.recovery,
        rerank_url=arguments.rerank_url,
    )
    if arguments.no_rerank:
        settings = settings.with_overrides(reranker="none")
    return settings


def _hybrid(
    index: TextIndex,
    semantic: SemanticIndex,
    settings: RetrievalSettings,
    generation_model: str,
) -> HybridRetriever:
    return HybridRetriever(
        index,
        semantic,
        build_reranker(settings, generation_model),
        candidates=settings.candidates,
        recovery=settings.recovery,
    )


def _sandbox(action: str) -> dict[str, Any]:
    from .sandbox import SandboxRunner
    from .sandbox.preflight import checks
    from .sandbox.runtime import RuntimePaths, default_home
    from .sandbox.setup import setup

    paths = RuntimePaths(default_home())
    if action == "setup":
        return setup(paths)
    report: dict[str, Any] = {
        check.name: ("ok: " if check.ok else "FAIL: ") + check.detail
        + (f" ({check.fix})" if check.fix else "")
        for check in checks(paths)
    }
    if all(value.startswith("ok") for value in report.values()):
        result = SandboxRunner(paths.home).run({"main.py": 'print("hello from the sandbox")'})
        report["test run"] = (
            f"ok: {result.stdout.strip()!r} in {result.duration_s} s, {result.peak_memory_mb} MB"
            if result.ok else f"FAIL: {result.crashed or result.stderr[-200:]}"
        )
    return report


def _dispatch(arguments: argparse.Namespace) -> tuple[Any, str]:
    if arguments.command == "sandbox":
        return _sandbox(arguments.action), "mapping"
    if arguments.command == "eval-find":
        from .find_evals import DEVELOPMENT_SEEDS, HOLDOUT_SEEDS, run_find_eval

        report = run_find_eval(
            DEVELOPMENT_SEEDS if arguments.split == "development" else HOLDOUT_SEEDS
        )
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report = {key: value for key, value in report.items() if key != "failures"} | {
            "failures": len(report["failures"])
        }
        return report, "mapping"
    if arguments.command == "eval-web":
        from .web_evals import load_cases, run_web_eval

        cases_path = arguments.cases or Path(
            "evals/web_adversarial_cases.json" if arguments.split.startswith("adversarial")
            else "evals/web_cases.json")
        report = run_web_eval(load_cases(cases_path, arguments.split), max(1, arguments.runs))
        report["configuration"] = {"cases": str(cases_path), "split": arguments.split}
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                        encoding="utf-8")
        return report["summary"], "mapping"
    settings = _retrieval_settings(arguments)
    index = TextIndex(arguments.database)
    if arguments.command == "doctor":
        return TerminalSession(arguments.database).doctor(), "mapping"
    if arguments.command == "index":
        return index.index_root(arguments.root), "mapping"
    if arguments.command == "search":
        return index.search(arguments.query, arguments.limit), "search"
    if arguments.command == "find":
        return FileFinder(index).find(arguments.query, arguments.limit), "find"
    if arguments.command == "embed":
        semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.model)
        return semantic.embed_pending(arguments.batch_size), "mapping"
    if arguments.command in ("semantic-search", "hybrid-search"):
        semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.model)
        backend = (
            semantic
            if arguments.command == "semantic-search"
            else _hybrid(index, semantic, settings, DEFAULT_MODEL)
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
            settings=settings,
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
        return _run_eval(arguments, index, settings), "evaluation"
    if arguments.command == "eval-retrieval":
        return _run_retrieval_eval(arguments, index, settings), "retrieval_evaluation"
    if arguments.command == "eval-chat":
        cases = load_coding_cases(arguments.cases)
        if arguments.case_ids:
            requested = set(arguments.case_ids)
            cases = [case for case in cases if case.identifier in requested]
            missing = requested - {case.identifier for case in cases}
            if missing:
                raise ValueError(f"Unknown coding case(s): {', '.join(sorted(missing))}")
        if arguments.limit:
            cases = cases[: arguments.limit]
        assistant = ToolCallingAssistant(
            OllamaClient(),
            ToolRegistry(weather=OpenMeteoWeatherProvider(), include_search=False),
            model=arguments.model,
            system_prompt=(
                f"{CHAT_SYSTEM_PROMPT}\n\n"
                f"{personality_prompt(PersonalitySettings.load(arguments.database.resolve().parent / 'kiki-personality.json'))}"
            ),
        )
        receipt = run_coding_evaluation(
            cases, lambda prompt: assistant.ask(prompt).answer
        )
        receipt["configuration"] = {
            "cases": str(arguments.cases.resolve()),
            "model": arguments.model,
        }
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return receipt, "coding_evaluation"
    if arguments.command == "eval-behavior":
        cases = load_behavior_cases(arguments.cases)
        if arguments.case_ids:
            requested = set(arguments.case_ids)
            cases = [case for case in cases if case.identifier in requested]
            missing = requested - {case.identifier for case in cases}
            if missing:
                raise ValueError(f"Unknown behavior case(s): {', '.join(sorted(missing))}")
        if arguments.limit:
            cases = cases[: arguments.limit]
        assistant = ToolCallingAssistant(
            OllamaClient(),
            ToolRegistry(weather=OpenMeteoWeatherProvider(), include_search=False),
            model=arguments.model,
            system_prompt=(
                f"{CHAT_SYSTEM_PROMPT}\n\n"
                f"{personality_prompt(PersonalitySettings())}"
            ),
        )
        receipt = run_behavior_evaluation(
            cases, lambda prompt: assistant.ask(prompt).answer
        )
        receipt["configuration"] = {
            "cases": str(arguments.cases.resolve()),
            "model": arguments.model,
        }
        if arguments.output:
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            arguments.output.write_text(
                json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return receipt, "behavior_evaluation"
    raise ValueError(f"Unknown command: {arguments.command}")


def _run_retrieval_eval(
    arguments: argparse.Namespace, index: TextIndex, settings: RetrievalSettings
) -> dict[str, Any]:
    cases = load_retrieval_cases(arguments.cases)
    if arguments.split != "all":
        cases = [case for case in cases if case.split == arguments.split]
    if not cases:
        raise ValueError("No evaluation cases matched the selected split")
    methods = [method.strip() for method in arguments.methods.split(",") if method.strip()]
    unknown = set(methods) - {"lexical", "hybrid", "rerank", "grader", "llama-cpp", "qwen3-reranker"}
    if unknown or not methods:
        raise ValueError(f"Unknown retrieval methods: {', '.join(sorted(unknown)) or 'none'}")
    if set(methods) - {"lexical"} and not index.embedding_count(arguments.embedding_model):
        raise ValueError("This database has no embeddings for the selected model")
    limit = arguments.limit or settings.passages
    semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.embedding_model)
    method_settings = {
        "hybrid": settings.with_overrides(reranker="none"),
        "rerank": settings,
        "grader": settings.with_overrides(
            reranker="grader",
            rerank_model=settings.rerank_model if settings.reranker == "grader" else "",
        ),
        "llama-cpp": settings.with_overrides(
            reranker="llama-cpp",
            rerank_model=settings.rerank_model if settings.reranker == "llama-cpp" else "",
        ),
        "qwen3-reranker": settings.with_overrides(
            reranker="qwen3-reranker",
            rerank_model=settings.rerank_model if settings.reranker == "qwen3-reranker" else "",
        ),
    }
    backends: dict[str, Any] = {}
    for method in methods:
        if method == "lexical":
            backends[method] = index
        else:
            backends[method] = _hybrid(index, semantic, method_settings[method], arguments.model)
    with GpuMemorySampler() as gpu:
        started = perf_counter()
        receipt = run_retrieval_evaluation(cases, backends, limit=limit)
        wall_seconds = perf_counter() - started
    receipt["resources"] = {"wall_seconds": round(wall_seconds, 1), "gpu_memory": gpu.report()}
    receipt["configuration"] = {
        "database": str(arguments.database.resolve()),
        "cases": str(arguments.cases.resolve()),
        "split": arguments.split,
        "limit": limit,
        "embedding_model": arguments.embedding_model,
        "generation_model": arguments.model,
        "methods": {
            method: (
                {"retriever": "lexical"}
                if method == "lexical"
                else method_settings[method].describe(arguments.model)
            )
            for method in methods
        },
    }
    receipt["environment"] = evaluation_environment(
        arguments.database,
        arguments.cases,
        models=[
            arguments.embedding_model,
            arguments.model,
            *(
                method_settings[method].resolved_rerank_model(arguments.model) or ""
                for method in methods
                if method != "lexical"
            ),
        ],
    )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return receipt


def _run_eval(
    arguments: argparse.Namespace, index: TextIndex, settings: RetrievalSettings
) -> dict[str, Any]:
    cases = load_cases(arguments.cases)
    if arguments.split != "all":
        cases = [case for case in cases if case.split == arguments.split]
    if not cases:
        raise ValueError("No evaluation cases matched the selected split")
    if not index.embedding_count(arguments.embedding_model):
        raise ValueError("This database has no embeddings for the selected model")

    semantic = SemanticIndex(index, OllamaEmbeddingClient(), arguments.embedding_model)
    hybrid = _hybrid(index, semantic, settings, arguments.model)
    ask_model = None
    if arguments.with_model:
        assistant = ToolCallingAssistant(
            OllamaClient(),
            ToolRegistry(hybrid),
            model=arguments.model,
            pre_retrieve=True,
            system_prompt=RAG_SYSTEM_PROMPT,
            passages=settings.passages,
            max_evidence_characters=settings.context_characters,
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
        "retrieval": settings.describe(arguments.model),
    }
    receipt["environment"] = evaluation_environment(
        arguments.database,
        arguments.cases,
        models=[
            arguments.embedding_model,
            arguments.model,
            settings.resolved_rerank_model(arguments.model) or "",
        ],
    )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return receipt


def _json_safe(output: Any) -> Any:
    if hasattr(output, "to_dict"):
        return output.to_dict()
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
    elif kind == "find":
        render_find_results(console, output)
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
    elif kind == "retrieval_evaluation":
        _render_retrieval_evaluation(console, output)
    elif kind == "coding_evaluation":
        _render_coding_evaluation(console, output)
    elif kind == "behavior_evaluation":
        _render_behavior_evaluation(console, output)
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


def _render_retrieval_evaluation(console: Console, receipt: dict[str, Any]) -> None:
    summary = Table(title="Passage-level retrieval", show_lines=True)
    for column in ("Method / split", "Cases", "Hit@1", "All evidence@k", "MRR", "Mean ms"):
        summary.add_column(column, justify="left" if column == "Method / split" else "right")
    for name, row in receipt["summary"].items():
        summary.add_row(
            name,
            str(row["cases"]),
            str(row["hit_at_1"]),
            str(row["full_at_k"]),
            f"{row['mrr']:.3f}",
            f"{row['mean_ms']:.0f}",
        )
    console.print(summary)
    misses = [row for row in receipt["cases"] if not row["full_at_k"]]
    if misses:
        table = Table(title="Cases missing evidence in the top results", show_lines=True)
        table.add_column("Method")
        table.add_column("Case")
        table.add_column("Split")
        table.add_column("First evidence rank", justify="right")
        for row in misses:
            table.add_row(
                row["method"], row["id"], row["split"], str(row["first_evidence_rank"] or "—")
            )
        console.print(table)
    console.print(
        "[dim]Evidence phrases mark passages that answer each question; hit@1 and MRR "
        "measure ranking, not answer correctness.[/dim]"
    )


def _render_coding_evaluation(console: Console, receipt: dict[str, Any]) -> None:
    render_mapping(console, "Coding regression summary", receipt["summary"])
    table = Table(title="Medium/hard coding cases", show_lines=True)
    table.add_column("Case")
    table.add_column("Level")
    table.add_column("No refusal")
    table.add_column("Concepts")
    table.add_column("Code")
    table.add_column("Syntax")
    table.add_column("Overall")
    for case in receipt["cases"]:
        table.add_row(
            case["id"],
            case["difficulty"],
            _mark(case["no_false_refusal"]),
            _mark(case["concept_signals_passed"]),
            _mark(case["has_code"]),
            _mark(case["python_syntax_valid"]),
            _mark(case["passed"]),
        )
    console.print(table)
    console.print(
        "[dim]This checks refusal behavior and expected algorithm signals. "
        "Generated code is not executed without a dedicated sandbox.[/dim]"
    )


def _render_behavior_evaluation(console: Console, receipt: dict[str, Any]) -> None:
    render_mapping(console, "Behavior regression summary", receipt["summary"])
    table = Table(title="Benign behavior cases", show_lines=True)
    table.add_column("Case")
    table.add_column("No refusal")
    table.add_column("No persona leak")
    table.add_column("Scope respected")
    table.add_column("Natural opening")
    table.add_column("Concise")
    table.add_column("Content signals")
    table.add_column("Overall")
    for case in receipt["cases"]:
        table.add_row(
            case["id"],
            _mark(case["no_false_refusal"]),
            _mark(case["no_persona_leak"]),
            _mark(case["no_forbidden_content"]),
            _mark(case["natural_opening"]),
            _mark(case["within_word_limit"]),
            _mark(case["required_signals_passed"]),
            _mark(case["passed"]),
        )
    console.print(table)
    console.print(
        "[dim]This checks benign over-refusal, concrete preference leakage, and "
        "basic answer signals. Human review still matters.[/dim]"
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
