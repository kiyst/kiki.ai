"""`/apply FILE`: save the last answer's code to a file, after you approve a diff.

Writes happen only inside a workspace folder you chose this session, only
after you see the full unified diff and answer yes, and never from the
sandbox. The previous version is backed up first. The model cannot invoke
this; it is a slash command.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from glob import escape as glob_escape
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .codeblocks import displayed_blocks, hidden_code
from .permissions import LOCAL_WRITE, requires_confirmation
from .safety import has_controls, protected_folder_reason, visible_controls

MAX_BYTES = 2 * 1024 * 1024
# Names Windows treats as devices in any folder and with any extension.
_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?$",
                     re.IGNORECASE)


class ApplyError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    target: Path
    before: str | None
    after: str
    diff: str
    workspace: Path | None = None

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
    """(language tag, code) of the last block the rendered answer displays."""
    blocks = displayed_blocks(answer)
    return (blocks[-1].language, blocks[-1].code) if blocks else None


def _check_name(argument: Path) -> None:
    """Refuse names Windows would turn into devices, streams, or silently rename."""
    parts = argument.parts[1:] if argument.anchor else argument.parts
    for part in parts:
        if part in {".", ".."}:
            continue  # resolved below; leaving the workspace is refused there
        if _DEVICE.match(part.strip()):
            raise ApplyError(f"{part} is a reserved Windows device name")
        if ":" in part:
            raise ApplyError(f"{part}: file names can't contain ':'")
        if part != part.rstrip(". "):
            raise ApplyError(f"{part!r}: file names can't end with a dot or a space")


def resolve_target(workspace: Path, argument: Path) -> Path:
    """The file to write, which must resolve to a place inside the workspace."""
    _check_name(argument)
    root = workspace.resolve()
    target = (argument if argument.is_absolute() else root / argument).resolve()
    if target != root and root not in target.parents:
        raise ApplyError(f"{argument} is outside the workspace {root}")
    if target == root or target.is_dir():
        raise ApplyError(f"{argument} is a folder; name a file")
    if not target.parent.is_dir():
        raise ApplyError(f"Folder does not exist: {target.parent}")
    # The folder actually written into is checked too, not just the workspace:
    # a broad workspace (C:\Users) otherwise reached the Startup folder or a
    # PowerShell profile inside it (re-audit).
    refused = protected_folder_reason(target.parent, writing=True)
    if refused and target.parent != root:
        raise ApplyError(f"Kiki won't write into {target.parent}: {refused}")
    return target


def plan_change(target: Path, code: str, workspace: Path | None = None) -> Change:
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
    return Change(target, before, after, diff, workspace)


def write_change(change: Change, backups: Path) -> Path | None:
    """Back up the old version, then replace the file atomically. Returns the backup."""
    # The path is checked again at write time: a folder swapped for a junction
    # while the prompt waited must not redirect the write (audit L).
    if change.workspace is not None and resolve_target(change.workspace, change.target) != change.target:
        raise ApplyError(f"{change.target.name} moved outside the workspace; run /apply again")
    current = change.target.read_bytes().decode("utf-8", "replace") if change.target.exists() else None
    if current != change.before:
        raise ApplyError(f"{change.target.name} changed after the diff was shown; run /apply again")
    backup = None
    if change.before is not None:
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        # One folder of backups per target folder, so same-named files in
        # different places don't share (or prune) each other's backups.
        folder = backups / hashlib.sha256(str(change.target.parent).casefold().encode()).hexdigest()[:12]
        folder.mkdir(parents=True, exist_ok=True)
        backup = folder / f"{change.target.name}.{stamp}.bak"
        backup.write_bytes(change.target.read_bytes())
        _prune_backups(folder, change.target.name)
    handle, temporary = tempfile.mkstemp(prefix=".kiki-apply-", dir=change.target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(change.after)
        os.replace(temporary, change.target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return backup


KEEP_BACKUPS = 20


def _prune_backups(backups: Path, name: str) -> None:
    """Keep the newest KEEP_BACKUPS backups of one file name (audit L: they grew forever).

    Matched exactly ("main" must not match "main.py"'s backups; re-audit)."""
    exact = re.compile(re.escape(name) + r"\.\d{8}-\d{6}-\d{6}\.bak")
    stamped = sorted((path for path in backups.glob(f"{glob_escape(name)}.*.bak") if exact.fullmatch(path.name)),
                     key=lambda path: path.name, reverse=True)
    for old in stamped[KEEP_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass


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
    # Prompts are plain text: markup off, so [y/N] and file names show as typed.
    read = read or (lambda prompt: console.input(prompt, markup=False))
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
    if has_controls(code):
        # Raw control characters can redraw the diff to hide what is saved (audit A3).
        console.print(Text("This code contains invisible control characters (such as ESC) that "
                           "could disguise what it does, so Kiki won't save it.", style="yellow"))
        return None
    if hidden_code(answer or ""):
        console.print(Text("This answer also contains code that isn't displayed (for example "
                           "inside an HTML comment); Kiki ignores it.", style="yellow"))
    try:
        target = resolve_target(workspace, argument)
        change = plan_change(target, code, workspace)
    except (ApplyError, OSError) as exc:
        console.print(Text(str(exc), style="yellow"))
        return None
    if change.unchanged:
        console.print(Text(f"{target} already matches; nothing to apply.", style="dim"))
        return None

    added, removed = change.counts()
    title = (f"New file {target}" if change.created else f"Changes to {target}")
    # The existing file may hold control characters; show them, don't act on them.
    console.print(Panel(Syntax(visible_controls(change.diff), "diff", word_wrap=True),
                        title=Text(title), border_style="cyan"))
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
        console.print(Panel(Text(str(exc)), title="Could not write", border_style="red"))
        return None
    message = Text.assemble(("Wrote ", "green"), str(target))
    if backup:
        message.append(f"\nPrevious version saved to {backup}", style="dim")
    console.print(message)
    return target
