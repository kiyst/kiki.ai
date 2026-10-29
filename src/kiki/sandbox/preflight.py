"""Fail-closed checks. Any failure means no execution, with the fix named."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from ..resilience import ErrorCode, KikiError
from . import jobs
from .runtime import PYTHON, WASMTIME_VERSION, RuntimePaths
from .wasi import sha256_file, tree_sha256

SETUP_HINT = "Run `kiki sandbox setup`."


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def read_manifest(paths: RuntimePaths) -> dict[str, Any] | None:
    try:
        return json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def checks(paths: RuntimePaths, *, verify_hashes: bool = True) -> list[Check]:
    results = [
        Check("platform", jobs.supported(), "Windows Job Objects available"
              if jobs.supported() else "Only Windows is supported for now",
              "" if jobs.supported() else "Run Kiki's sandbox on Windows"),
    ]
    try:
        installed = metadata.version("wasmtime")
    except metadata.PackageNotFoundError:
        installed = None
    results.append(Check(
        "wasmtime", installed == WASMTIME_VERSION,
        f"wasmtime {installed or 'not installed'} (needs {WASMTIME_VERSION})",
        "" if installed == WASMTIME_VERSION else f'pip install "wasmtime=={WASMTIME_VERSION}"'))

    manifest = read_manifest(paths)
    expected = manifest is not None and manifest.get("runtime") == f"{PYTHON.name}-{PYTHON.version}"
    results.append(Check("runtime manifest", expected,
                         str(paths.manifest) if expected else "missing or for another version",
                         "" if expected else SETUP_HINT))
    if not expected:
        return results
    assert manifest is not None
    for name, path, key in (("python.wasm", paths.wasm, "python_wasm_sha256"),
                            ("compiled runtime", paths.compiled, "compiled_sha256")):
        if not path.exists():
            results.append(Check(name, False, f"{path} is missing", SETUP_HINT))
        elif verify_hashes and sha256_file(path) != manifest.get(key):
            results.append(Check(name, False, "checksum does not match the manifest", SETUP_HINT))
        else:
            results.append(Check(name, True, "present" + (", checksum verified" if verify_hashes else "")))
    packages_ok = paths.packages.is_dir() and (
        not verify_hashes or tree_sha256(paths.packages) == manifest.get("packages_sha256"))
    names = ", ".join(f"{name} {info['version']}" for name, info in manifest.get("packages", {}).items())
    results.append(Check("packages", packages_ok, names or "none",
                         "" if packages_ok else SETUP_HINT))
    library = paths.lib / f"python{'.'.join(PYTHON.version.split('.')[:2])}"
    results.append(Check("standard library", library.is_dir(), str(library),
                         "" if library.is_dir() else SETUP_HINT))
    return results


def require(paths: RuntimePaths) -> dict[str, Any]:
    """Return the manifest if every check passes; otherwise refuse."""
    failed = [check for check in checks(paths) if not check.ok]
    if failed:
        first = failed[0]
        raise KikiError(
            f"Code execution is unavailable: {first.name}: {first.detail}. {first.fix}".strip(),
            code=ErrorCode.SERVICE_UNAVAILABLE,
            details={"failed": [check.name for check in failed]},
        )
    manifest = read_manifest(paths)
    assert manifest is not None
    return manifest
