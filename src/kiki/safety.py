"""Folders Kiki must never index or write into, and display-safe text.

Shared by /folders add (reading) and /workspace (where /apply writes). Both
refuse whole drives and system folders; /workspace also refuses the home
folder itself and the Startup folder, where a written file runs on its own.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

# C0 and C1 control characters other than newline and tab, plus escape:
# they can clear the screen, move the cursor, set the clipboard (OSC 52), or
# draw fake links when printed to a terminal.
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def visible_controls(text: str) -> str:
    """Text with control characters shown as \\xNN instead of acted on by the terminal."""
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", text)


def has_controls(text: str) -> bool:
    """True when text holds control characters other than newline, tab, and carriage return."""
    return bool(re.search("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", text))


def _system_folders() -> list[Path]:
    names = ["SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432",
             "ProgramData", "APPDATA", "LOCALAPPDATA"]
    folders = [Path(os.environ[name]) for name in names if os.environ.get(name)]
    home = Path.home()
    folders += [home / "AppData"]
    return folders


def _normal(path: Path) -> str:
    text = str(path.expanduser().resolve(strict=False))
    if text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(text.rstrip("\\/")) or text


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def protected_folder_reason(path: Path, *, writing: bool = False) -> str | None:
    """Why `path` must not be indexed (or, with writing, written into), or None."""
    resolved = Path(_normal(path))
    if resolved == Path(resolved.anchor) or str(resolved).rstrip("\\/") in {resolved.drive, ""}:
        return "that is a whole drive; add the folders you need instead"
    name = resolved.name.casefold()
    if name in {"$recycle.bin", "system volume information"}:
        return "that is a system folder"
    normal = _normal(path)
    temporary = _normal(Path(tempfile.gettempdir()))
    for folder in _system_folders():
        # The temporary folder sits inside AppData but holds nothing sensitive.
        if _inside(normal, _normal(folder)) and not _inside(normal, temporary):
            return f"that is inside a system or application folder ({folder})"
    if writing:
        home = _normal(Path.home())
        if normal == home:
            return "that is your whole home folder; choose a project folder inside it"
        if "startup" in Path(normal).parts[-1:] or "\\start menu\\" in normal + "\\":
            return "files written there run automatically when you sign in"
    return None
