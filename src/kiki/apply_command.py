"""`/apply FILE`: save the last answer's code to a file, after you approve a diff.

Writes happen only inside a workspace folder you chose this session, only
after you see the full unified diff and answer yes, and never from the
sandbox. The previous version is backed up first. The model cannot invoke
this; it is a slash command.
"""

from __future__ import annotations

import difflib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .permissions import LOCAL_WRITE, requires_confirmation

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+.#-]*)[^\n]*\n(.*?)```", re.DOTALL)
MAX_BYTES = 2 * 1024 * 1024


class ApplyError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    target: Path
    before: str | None
    after: str
    diff: str

    @property
    def created(self) -> bool:
        return self.before is None

    @property
    def unchanged(self) -> bool:
        return self.before == self.after

    def counts(self) -> tuple[int, int]:
        lines = self.diff.splitlines()
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        return added, removed


def last_code_block(answer: str) -> tuple[str, str] | None:
    """(language tag, code) of the last fenced block, any language."""
    blocks = [(tag, body) for tag, body in _FENCE.findall(answer) if body.strip()]
    if not blocks:
        return None
    tag, body = blocks[-1]
    return tag.casefold(), body.rstrip() + "\n"


def resolve_target(workspace: Path, argument: Path) -> Path:
    """The file to write, which must resolve to a place inside the workspace."""
    root = workspace.resolve()
    target = (argument if argument.is_absolute() else root / argument).resolve()
    if target != root and root not in target.parents:
        raise ApplyError(f"{argument} is outside the workspace {root}")
    if target == root or target.is_dir():
        raise ApplyError(f"{argument} is a folder; name a file")
    if not target.parent.is_dir():
        raise ApplyError(f"Folder does not exist: {target.parent}")
    return target


def plan_change(target: Path, code: str) -> Change:
    before: str | None = None
    newline = "\n"
    if target.exists():
        if target.stat().st_size > MAX_BYTES:
            raise ApplyError(f"{target.name} is too large to edit here")
        raw = target.read_bytes()
        try:
            before = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ApplyError(f"{target.name} is not a UTF-8 text file") from None
        if "\r\n" in before:
            newline = "\r\n"
    if len(code.encode("utf-8")) > MAX_BYTES:
        raise ApplyError("The code block is too large")
    after = code.replace("\r\n", "\n")
    if newline == "\r\n":
        after = after.replace("\n", "\r\n")
    diff = "".join(difflib.unified_diff(
        (before or "").replace("\r\n", "\n").splitlines(keepends=True),
        after.replace("\r\n", "\n").splitlines(keepends=True),
        fromfile="/dev/null" if before is None else f"a/{target.name}",
        tofile=f"b/{target.name}",
    ))
    return Change(target, before, after, diff)


def write_change(change: Change, backups: Path) -> Path | None:
    """Back up the old version, then replace the file atomically. Returns the backup."""
    current = change.target.read_bytes().decode("utf-8", "replace") if change.target.exists() else None
    if current != change.before:
        raise ApplyError(f"{change.target.name} changed after the diff was shown; run /apply again")
    backup = None
    if change.before is not None:
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = backups / f"{change.target.name}.{stamp}.bak"
        backup.write_bytes(change.target.read_bytes())
    handle, temporary = tempfile.mkstemp(prefix=".kiki-apply-", dir=change.target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(change.after)
        os.replace(temporary, change.target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return backup


def apply_command(
    console: Console,
    *,
    answer: str | None,
    workspace: Path | None,
    argument: Path | None,
    backups: Path,
    read: Callable[[str], str] | None = None,
) -> Path | None:
    """Show the diff, ask, and write. Returns the written path, or None."""
    read = read or console.input
    if workspace is None:
        console.print("[yellow]Choose a workspace first:[/yellow] [bold]/workspace PATH[/bold] or "
                      "[bold]/workspace browse[/bold]. Kiki only writes inside it.")
        return None
    if argument is None:
        console.print("[yellow]Usage: /apply FILE[/yellow] (a path inside the workspace)")
        return None
    block = last_code_block(answer or "")
    if block is None:
        console.print("[yellow]The last answer has no code block to apply.[/yellow]")
        return None
    language, code = block
    try:
        target = resolve_target(workspace, argument)
        change = plan_change(target, code)
    except (ApplyError, OSError) as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return None
    if change.unchanged:
        console.print(f"[dim]{target} already matches; nothing to apply.[/dim]")
        return None

    added, removed = change.counts()
    title = (f"New file {target}" if change.created else f"Changes to {target}")
    console.print(Panel(Syntax(change.diff, "diff", word_wrap=True), title=title,
                        border_style="cyan"))
    summary = f"+{added} −{removed} lines" + (f" · from a {language} block" if language else "")
    console.print(Text(f"{summary}. The current version is backed up before writing.", style="dim"))
    if requires_confirmation(LOCAL_WRITE):
        reply = read(f"Write this to {target.name}? [y/N] ").strip().casefold()
        if reply not in {"y", "yes"}:
            console.print("[dim]Not written.[/dim]")
            return None
    try:
        backup = write_change(change, backups)
    except (ApplyError, OSError) as exc:
        console.print(Panel(str(exc), title="Could not write", border_style="red"))
        return None
    message = f"[green]Wrote[/green] {target}"
    if backup:
        message += f"\n[dim]Previous version saved to {backup}[/dim]"
    console.print(message)
    return target
