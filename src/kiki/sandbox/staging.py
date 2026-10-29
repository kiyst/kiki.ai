"""Disposable per-run input folders, written only from text held in memory."""

from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from .limits import RunLimits

PREFIX = "kiki-run-"
LAUNCHER_NAME = "kiki_launcher.py"
# Flat names only: no folders, no "..", no drive letters, no hidden files.
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")

LAUNCHER = """import runpy, sys
sys.path.insert(0, "/input")
sys.argv = [{entry!r}]
runpy.run_path("/input/" + {entry!r}, run_name="__main__")
"""


class StagingError(ValueError):
    pass


def validate(files: Mapping[str, str], entry: str, limits: RunLimits) -> None:
    if not files:
        raise StagingError("Nothing to run: no files were given")
    if len(files) > limits.max_files:
        raise StagingError(f"Too many files: {len(files)} (limit {limits.max_files})")
    total = 0
    for name, text in files.items():
        if not _NAME.match(name) or name.endswith("."):
            raise StagingError(f"File name not allowed: {name!r}")
        if name == LAUNCHER_NAME:
            raise StagingError(f"File name is reserved: {name!r}")
        if not isinstance(text, str):
            raise StagingError(f"File contents must be text: {name!r}")
        total += len(text.encode("utf-8"))
    if total > limits.max_input_bytes:
        raise StagingError(f"Files are too large: {total} bytes (limit {limits.max_input_bytes})")
    if entry not in files or not entry.endswith(".py"):
        raise StagingError(f"Entry point must be one of the given .py files: {entry!r}")


def stage(files: Mapping[str, str], entry: str, limits: RunLimits) -> Path:
    """Create a fresh folder holding the files and Kiki's launcher."""
    validate(files, entry, limits)
    folder = Path(tempfile.mkdtemp(prefix=PREFIX))
    try:
        for name, text in files.items():
            (folder / name).write_text(text, encoding="utf-8", newline="\n")
        (folder / LAUNCHER_NAME).write_text(LAUNCHER.format(entry=entry), encoding="utf-8")
    except BaseException:
        remove(folder)
        raise
    return folder


def remove(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
    folder.with_suffix(".json").unlink(missing_ok=True)


def sweep(min_age_s: float = 15 * 60) -> int:
    """Remove leftovers from runs that ended abnormally. Returns the count.

    Only folders older than any possible run are touched, so a run in
    progress (here or in another Kiki process) is never deleted.
    """
    removed = 0
    cutoff = time.time() - min_age_s
    for path in Path(tempfile.gettempdir()).glob(f"{PREFIX}*"):
        try:
            if path.stat().st_mtime > cutoff:
                continue
        except FileNotFoundError:
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        removed += not path.exists()
    return removed
