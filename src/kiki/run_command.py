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

from .codeblocks import CodeBlock, displayed_blocks, hidden_code
from .permissions import EXECUTE, requires_confirmation
from .safety import has_controls, visible_controls
from .resilience import KikiError
from .sandbox import RunLimits, RunResult, SandboxRunner
from .sandbox.staging import StagingError

_PYTHON_TAGS = {"python", "py", "python3"}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\.py$")


def python_block(answer: str) -> CodeBlock | None:
    """The last displayed Python block; untagged blocks only if none are tagged Python."""
    blocks = displayed_blocks(answer)
    tagged = [block for block in blocks if block.language in _PYTHON_TAGS]
    untagged = [block for block in blocks if not block.language]
    chosen = tagged or untagged
    return chosen[-1] if chosen else None


def code_from_answer(answer: str) -> str | None:
    block = python_block(answer)
    return block.code if block else None


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
    # Prompts are plain text: markup off, so [y/N] and file names show as typed.
    read = read or (lambda prompt: console.input(prompt, markup=False))
    runner = runner or SandboxRunner()
    limits = runner.limits
    try:
        if argument is not None:
            name, code = code_from_file(argument, limits)
            source = f"a copy of {argument}"
        else:
            block = python_block(answer or "")
            if block is None:
                console.print("[yellow]The last answer has no Python code block to run.[/yellow] "
                              "Use [bold]/run FILE.py[/bold] to run a file.")
                return None
            code, name = block.code, "main.py"
            source = "the last answer" + (f" (block {block.number} of {block.total})"
                                          if block.total > 1 else "")
            if hidden_code(answer or ""):
                console.print(Text("This answer also contains code that isn't displayed (for "
                                   "example inside an HTML comment); Kiki ignores it.", style="yellow"))
    except (StagingError, OSError, UnicodeDecodeError) as exc:
        console.print(Text(str(exc), style="yellow"))
        return None
    if has_controls(code):
        # Raw control characters can redraw the preview to hide what runs (audit A2-A3).
        console.print(Text("This code contains invisible control characters (such as ESC) that "
                           "could disguise what it does, so Kiki won't run it.", style="yellow"))
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
        console.print(Text(str(exc), style="yellow"))
        return None
    except KikiError as exc:
        console.print(Panel(Text(str(exc)), title="Could not run", border_style="red"))
        return None
    render_run_result(console, result, limits)
    return result


def _preview(console: Console, code: str, *, source: str, mode: str, limits: RunLimits) -> None:
    # All of it: approval covers every line, so every line is shown (audit A15).
    console.print(Panel(Syntax(code.rstrip("\n"), "python", line_numbers=True, word_wrap=True),
                        title=Text(f"Code from {source} · {len(code.splitlines())} lines"),
                        border_style="cyan"))
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
        status, style = f"Crashed: {visible_controls(result.crashed)}", "red"
    elif result.exit_code == 0:
        status, style = "Finished", "green"
    else:
        status, style = f"Exited with code {result.exit_code}", "red"
    body = Text()
    body.append(f"{status} · {result.duration_s:.1f} s · {result.peak_memory_mb:.0f} MB\n",
                style=f"bold {style}")
    # Output is shown, never acted on: control characters appear as \x1b text,
    # so code can't clear the screen, set the clipboard, or fake a prompt (audit A2).
    if result.stdout:
        body.append("\n" + visible_controls(result.stdout.rstrip()) + "\n")
    if result.stderr.strip():
        body.append("\n" + visible_controls(result.stderr.rstrip()[-4000:]) + "\n", style="red")
    if not result.stdout and not result.stderr.strip():
        body.append("\n(no output)\n", style="dim")
    if result.output_truncated:
        body.append("\nOutput was cut short.", style="dim")
    console.print(Panel(body, title="Sandbox run", border_style=style))
