"""wasmtime configuration shared by setup (compiling) and the worker (running).

Everything the guest can reach is decided here, from fixed values.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

# functools.cache recursion goes through C frames; wasmtime's 512 KiB default
# traps below 500 levels. 2 MiB (wasmtime's async-stack ceiling) allows ~1,200
# per call (measured; 1,500 fails). Plain Python recursion is unaffected.
# It needs a host thread with a larger native stack than Windows' 1 MiB.
WASM_STACK_BYTES = 2 * 2**20
HOST_THREAD_STACK_BYTES = 16 * 2**20

GUEST_ARGV = ["python", "-I", "-B", "-X", "utf8", "/input/kiki_launcher.py"]
GUEST_ENV = [["PYTHONDONTWRITEBYTECODE", "1"], ["PYTHONUNBUFFERED", "1"]]


def grants(lib: Path, staging: Path, packages: Path) -> list[tuple[str, str, bool]]:
    """Host folder, guest path, writable. The only three; all read-only."""
    return [
        (str(lib), "/lib", False),
        (str(staging), "/input", False),
        (str(packages), "/packages", False),
    ]


def tree_sha256(root: Path) -> str:
    """One checksum over every file's relative path and contents."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(sha256_file(path).encode() + b"\n")
    return digest.hexdigest()


def engine_config() -> Any:
    import wasmtime

    config = wasmtime.Config()
    config.epoch_interruption = True
    config.max_wasm_stack = WASM_STACK_BYTES
    return config


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
