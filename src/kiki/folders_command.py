"""/folders: choose which folders Kiki indexes, from inside the chat.

Indexing only reads. Removing a folder forgets its index entries; the folder
and its files on disk are never touched.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from .retrieval import TextIndex

USAGE = ("Usage: /folders · /folders add PATH|browse · /folders reindex [NUMBER|all] · "
         "/folders remove NUMBER")


def folders_command(
    console: Console,
    index: TextIndex,
    argument: str,
    *,
    read: Callable[[str], str],
    browse: Callable[[], Path | None],
) -> bool:
    """Returns True when the index changed."""
    action, _, rest = argument.strip().partition(" ")
    action, rest = action.casefold(), rest.strip().strip("\"'")
    roots = index.roots()
    if not action:
        _show(console, roots)
        return False
    if action == "add":
        folder = browse() if not rest or rest.casefold() == "browse" else Path(rest).expanduser()
        if folder is None:
            console.print("[dim]No folder added.[/dim]")
            return False
        if not folder.is_dir():
            console.print(f"[yellow]Not a folder:[/yellow] {escape(str(folder))}")
            return False
        return _index(console, index, [folder.resolve()])
    if action == "reindex":
        if not roots:
            console.print("[yellow]No folders yet. /folders add PATH or /folders add browse.[/yellow]")
            return False
        if rest and rest.casefold() != "all":
            chosen = _pick(console, roots, rest)
            return chosen is not None and _index(console, index, [Path(chosen["path"])])
        return _index(console, index, [Path(root["path"]) for root in roots])
    if action == "remove":
        chosen = _pick(console, roots, rest)
        if chosen is None:
            return False
        answer = read(
            f"Forget {chosen['path']} ({chosen['files']:,} files) from Kiki's index? "
            "Your files are not touched. [y/N] "
        )
        if answer.strip().casefold() not in {"y", "yes"}:
            console.print("[dim]Kept.[/dim]")
            return False
        forgotten = index.remove_root(Path(chosen["path"]))
        console.print(f"[green]Forgot {forgotten:,} files from[/green] {escape(str(chosen['path']))}. "
                      "Nothing on disk changed.")
        return True
    console.print(f"[yellow]{USAGE}[/yellow]")
    return False


def _show(console: Console, roots: list[dict[str, Any]]) -> None:
    if not roots:
        console.print("No folders indexed yet. [bold]/folders add PATH[/bold] or "
                      "[bold]/folders add browse[/bold] picks one; Kiki only looks where you add.")
        return
    table = Table(title="Indexed folders")
    table.add_column("#", justify="right", style="cyan")
    table.add_column("Folder", overflow="fold")
    table.add_column("Files", justify="right")
    table.add_column("Readable", justify="right")
    table.add_column("Last indexed")
    for number, root in enumerate(roots, start=1):
        when = _when(root["indexed_at"])
        if not root["exists"]:
            when = "[red]folder missing[/red]"
        table.add_row(str(number), Text(str(root["path"])), f"{root['files']:,}", f"{root['readable']:,}", when)
    console.print(table)
    console.print("[dim]Kiki does not watch these folders yet: /folders reindex picks up "
                  "new, changed, and deleted files.[/dim]")


def _pick(console: Console, roots: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    if text.isdigit() and 1 <= int(text) <= len(roots):
        return roots[int(text) - 1]
    console.print(f"[yellow]Choose a folder number from /folders (1-{len(roots)}).[/yellow]"
                  if roots else "[yellow]No folders indexed yet.[/yellow]")
    return None


def _index(console: Console, index: TextIndex, folders: list[Path]) -> bool:
    changed = False
    for folder in folders:
        if not folder.is_dir():
            console.print(f"[yellow]Skipped, folder missing:[/yellow] {escape(str(folder))}")
            continue
        try:
            with console.status(f"Scanning {folder}…", spinner="dots") as status:
                counts = index.index_root(
                    folder,
                    progress=lambda done, total: status.update(
                        f"Reading {done:,} of {total:,} readable files in {folder.name}…"
                    ),
                )
        except KeyboardInterrupt:
            console.print(f"[yellow]Cancelled; nothing changed for[/yellow] {escape(str(folder))}.")
            continue
        except ValueError as exc:
            console.print(Text(str(exc), style="yellow"))
            continue
        changed = True
        _report(console, folder, counts)
    return changed


def _report(console: Console, folder: Path, counts: dict[str, Any]) -> None:
    readable = counts["indexed"] + counts["unchanged"]
    parts = [f"{counts['catalogued']:,} files listed for /find",
             f"{readable:,} readable ({counts['indexed']:,} new or changed)"]
    if counts["removed"]:
        parts.append(f"{counts['removed']:,} gone since last time")
    console.print(f"[green]Indexed[/green] {escape(str(folder))}: " + ", ".join(parts) + ".")
    problems = [issue for issue in counts["issues"] if "stopped at" not in issue["reason"]]
    if problems:
        console.print(f"[yellow]{len(problems):,} file(s) could not be read[/yellow] (still findable by name):")
        for issue in problems[:3]:
            console.print(Text(f"  {Path(issue['path']).name}: {issue['reason']}", style="dim"))
        if len(problems) > 3:
            console.print(f"  [dim]…and {len(problems) - 3:,} more[/dim]")
    for issue in counts["issues"]:
        if "stopped at" in issue["reason"]:
            console.print(f"[yellow]Very large folder: {escape(str(issue['reason']))}; the rest are not "
                          "indexed. Removing it and adding the folders you need is better.[/yellow]")


def _when(stamp: str | None) -> str:
    if not stamp:
        return "before this was tracked"
    return datetime.fromisoformat(stamp).astimezone().strftime("%Y-%m-%d %H:%M")
