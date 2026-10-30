"""`/run`: execute Python in the sandbox, only after the user confirms.

The code comes from the last answer's Python block or from a copy of a .py
file the user names. Nothing is written back; the model cannot invoke this.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .permissions import EXECUTE, requires_confirmation
from .resilience import KikiError
from .sandbox import RunLimits, RunResult, SandboxRunner
from .sandbox.staging import StagingError

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.DOTALL)
_PYTHON_TAGS = {"python", "py", "python3"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py$")
PREVIEW_LINES = 60


def code_from_answer(answer: str) -> str | None:
    """The last Python block; untagged blocks only if none are tagged Python."""
    blocks = [(tag.casefold(), body) for tag, body in _FENCE.findall(answer)]
    tagged = [body for tag, body in blocks if tag in _PYTHON_TAGS]
    untagged = [body for tag, body in blocks if not tag]
    chosen = (tagged or untagged)[-1:] if (tagged or untagged) else []
    return chosen[0].rstrip() + "\n" if chosen and chosen[0].strip() else None


def code_from_file(path: Path, limits: RunLimits) -> tuple[str, str]:
    """Read a copy of a .py file. Returns (name in the sandbox, text)."""
    if path.suffix.casefold() != ".py":
        raise StagingError(f"Only .py files can be run: {path.name}")
    if not path.is_file():
        raise StagingError(f"File not found: {path}")
    if path.stat().st_size > limits.max_input_bytes:
        raise StagingError(f"File is too large to run: {path.name}")
    text = path.read_text(encoding="utf-8")
    name = path.name if _SAFE_NAME.match(path.name) else "main.py"
    return name, text


def run_command(
    console: Console,
    *,
    answer: str | None,
    mode: str,
    argument: Path | None,
    read: Callable[[str], str] | None = None,
    runner: SandboxRunner | None = None,
) -> RunResult | None:
    """Preview, confirm, run, and show the result. Returns None if not run."""
    read = read or console.input
    runner = runner or SandboxRunner()
    limits = runner.limits
    try:
        if argument is not None:
            name, code = code_from_file(argument, limits)
            source = f"a copy of {argument}"
        else:
            code = code_from_answer(answer or "")
            if code is None:
                console.print("[yellow]The last answer has no Python code block to run.[/yellow] "
                              "Use [bold]/run FILE.py[/bold] to run a file.")
                return None
            name, source = "main.py", "the last answer"
    except (StagingError, OSError, UnicodeDecodeError) as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return None

    _preview(console, code, source=source, mode=mode, limits=limits)
    if requires_confirmation(EXECUTE):
        reply = read("Run this code in the sandbox? [y/N] ").strip().casefold()
        if reply not in {"y", "yes"}:
            console.print("[dim]Not run.[/dim]")
            return None
    try:
        with console.status("Running in the sandbox…", spinner="dots"):
            result = runner.run({name: code}, entry=name)
    except StagingError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return None
    except KikiError as exc:
        console.print(Panel(str(exc), title="Could not run", border_style="red"))
        return None
    render_run_result(console, result, limits)
    return result


def _preview(console: Console, code: str, *, source: str, mode: str, limits: RunLimits) -> None:
    lines = code.splitlines()
    shown = "\n".join(lines[:PREVIEW_LINES])
    if len(lines) > PREVIEW_LINES:
        shown += f"\n# … {len(lines) - PREVIEW_LINES} more lines"
    console.print(Panel(Syntax(shown, "python", line_numbers=True, word_wrap=True),
                        title=f"Code from {source}", border_style="cyan"))
    notes = [
        f"Runs in the sandbox on a temporary copy: no access to your files, no network, "
        f"stopped after {limits.timeout_s:g} s or {limits.memory_mib} MB. Nothing is saved.",
    ]
    if mode == "rag":
        notes.append("This answer was based on your documents; read the code before running it.")
    elif mode == "web":
        notes.append("This answer was based on a web page, which anyone could have written; "
                     "read the code before running it.")
    console.print(Text("\n".join(notes), style="dim"))


def render_run_result(console: Console, result: RunResult, limits: RunLimits) -> None:
    if result.timed_out:
        status, style = f"Stopped: the {limits.timeout_s:g} s time limit was reached", "yellow"
    elif result.output_killed:
        status, style = "Stopped: too much output (over 1 MB)", "yellow"
    elif result.memory_exceeded:
        status, style = f"Stopped: the {limits.memory_mib} MB memory limit was reached", "yellow"
    elif result.crashed:
        status, style = f"Crashed: {result.crashed}", "red"
    elif result.exit_code == 0:
        status, style = "Finished", "green"
    else:
        status, style = f"Exited with code {result.exit_code}", "red"
    body = Text()
    body.append(f"{status} · {result.duration_s:.1f} s · {result.peak_memory_mb:.0f} MB\n",
                style=f"bold {style}")
    if result.stdout:
        body.append("\n" + result.stdout.rstrip() + "\n")
    if result.stderr.strip():
        body.append("\n" + result.stderr.rstrip()[-4000:] + "\n", style="red")
    if not result.stdout and not result.stderr.strip():
        body.append("\n(no output)\n", style="dim")
    if result.output_truncated:
        body.append("\nOutput was cut short.", style="dim")
    console.print(Panel(body, title="Sandbox run", border_style=style))
