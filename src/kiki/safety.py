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


def offline_mode() -> bool:
    """KIKI_OFFLINE=1 (or true/yes/on) blocks every internet request Kiki makes."""
    return os.getenv("KIKI_OFFLINE", "").strip().casefold() in {"1", "true", "yes", "on"}


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
    folders.append(Path.home() / "AppData")
    return folders


# Folder names refused anywhere on a path: system areas, and (for writing)
# places where a written file is run or trusted without being opened.
_SYSTEM_NAMES = {"$recycle.bin", "system volume information", "windows.old", "$windows.~bt",
                 "$windows.~ws", "appdata"}
_AUTORUN_PARTS = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".git", ".vscode",
                  ".idea", "windowspowershell"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", ".", "?", os.environ.get("COMPUTERNAME", "").casefold()}


def _normal(path: Path) -> str:
    r"""A comparable local path: resolved, without \\?\, with loopback network
    paths (\\localhost\C$\Windows) turned back into drive paths, so the same
    folder can't be reached past the checks under another name (re-audit)."""
    text = str(path.expanduser())
    for prefix in ("\\\\?\\UNC\\", "\\\\.\\UNC\\"):
        if text.casefold().startswith(prefix.casefold()):
            text = "\\\\" + text[len(prefix):]
    if text.startswith("\\\\") and not text.startswith(("\\\\?\\", "\\\\.\\")):
        parts = text[2:].split("\\")
        if len(parts) >= 2 and parts[0].casefold() in _LOCAL_HOSTS and re.fullmatch(r"[A-Za-z]\$", parts[1]):
            text = parts[1][0] + ":\\" + "\\".join(parts[2:])
    text = str(Path(text).resolve(strict=False))
    if text.startswith(("\\\\?\\", "\\\\.\\")):
        text = text[4:]
    return os.path.normcase(text.rstrip("\\/")) or text


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def protected_folder_reason(path: Path, *, writing: bool = False) -> str | None:
    """Why `path` must not be indexed (or, with writing, written into), or None."""
    normal = _normal(path)
    resolved = Path(normal)
    if resolved == Path(resolved.anchor) or normal.rstrip("\\/") in {resolved.drive.casefold(), ""}:
        return "that is a whole drive; add the folders you need instead"
    if normal.startswith("\\\\") and writing:
        return "that is a network location; choose a folder on this computer"
    temporary = _normal(Path(tempfile.gettempdir()))
    # Inside the temporary folder (which sits in AppData), only the part below
    # it is judged.
    base = Path(temporary) if _inside(normal, temporary) else Path(resolved.anchor)
    parts = [part.casefold() for part in resolved.parts[len(base.parts):]]
    if any(part in _SYSTEM_NAMES for part in parts) or (
            base == Path(resolved.anchor) and parts[:1] == ["recovery"]):
        return "that is a system folder"
    for folder in _system_folders():
        # The temporary folder sits inside AppData but holds nothing sensitive.
        if _inside(normal, _normal(folder)) and not _inside(normal, temporary):
            return f"that is inside a system or application folder ({folder})"
    if writing:
        if normal == _normal(Path.home()):
            return "that is your whole home folder; choose a project folder inside it"
        if any(part in _AUTORUN_PARTS for part in parts) or (
                "start menu" in parts and "startup" in parts):
            return ("files written there can run or be trusted automatically (startup, "
                    "shell profiles, SSH, git or editor settings)")
        documents = [index for index, part in enumerate(parts) if part == "documents"]
        if any(parts[index + 1: index + 2] == ["powershell"] for index in documents):
            return "files written there run automatically when PowerShell starts"
    return None
