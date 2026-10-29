"""The single allowed runtime, pinned by version and checksum."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WASMTIME_VERSION = "50.0.1"


@dataclass(frozen=True)
class PythonRuntime:
    name: str
    version: str
    url: str
    zip_sha256: str


PYTHON = PythonRuntime(
    name="python-wasi",
    version="3.14.9",
    url=(
        "https://github.com/brettcannon/cpython-wasi-build/releases/download/"
        "v3.14.9/python-3.14.9-wasi_sdk-24.zip"
    ),
    zip_sha256="8de7834105edef8db8a13299e2587cf8945021dd8764f2691d83bbc25129dfa2",
)


@dataclass(frozen=True)
class Package:
    """A pure-Python package offered to sandboxed code, read-only."""

    name: str
    version: str
    url: str
    wheel_sha256: str
    top_level: str


# Allowlist. Pure Python only (nothing to compile), no dependencies. LeetCode's
# Python environment provides sortedcontainers, so solutions often import it.
PACKAGES: tuple[Package, ...] = (
    Package(
        name="sortedcontainers",
        version="2.4.0",
        url=(
            "https://files.pythonhosted.org/packages/32/46/"
            "9cb0e58b2deb7f82b84065f37f3bffeb12413f947f9388e4cac22c4621ce/"
            "sortedcontainers-2.4.0-py2.py3-none-any.whl"
        ),
        wheel_sha256="a163dcaede0f1c021485e957a39245190e74249897e2ae4b2aa38595db237ee0",
        top_level="sortedcontainers",
    ),
)


@dataclass(frozen=True)
class RuntimePaths:
    home: Path

    @property
    def archive(self) -> Path:
        return self.home / "python.zip"

    @property
    def root(self) -> Path:
        return self.home / "runtime"

    @property
    def wasm(self) -> Path:
        return self.root / "python.wasm"

    @property
    def lib(self) -> Path:
        return self.root / "lib"

    @property
    def compiled(self) -> Path:
        return self.home / f"python.wasm.wasmtime-{WASMTIME_VERSION}.compiled"

    @property
    def manifest(self) -> Path:
        return self.home / "manifest.json"

    @property
    def packages(self) -> Path:
        return self.home / "packages"

    @property
    def wheels(self) -> Path:
        return self.home / "wheels"


def default_home(runtime: PythonRuntime = PYTHON) -> Path:
    """%LOCALAPPDATA%\\kiki\\wasi-python\\<version>, or KIKI_SANDBOX_HOME."""
    override = os.environ.get("KIKI_SANDBOX_HOME")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "kiki" / "wasi-python" / runtime.version
