"""`kiki sandbox setup`: fetch, verify, unpack, and compile the pinned runtime.

Runs only when the user asks. An already-downloaded archive is reused if its
checksum matches.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .runtime import PYTHON, WASMTIME_VERSION, PythonRuntime, RuntimePaths
from .wasi import engine_config, sha256_file

Downloader = Callable[[str, Path], None]
Compiler = Callable[[Path, Path], None]


class SetupError(RuntimeError):
    pass


def download(url: str, target: Path) -> None:
    import httpx

    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with open(target, "wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def compile_module(wasm: Path, target: Path) -> None:
    import wasmtime

    engine = wasmtime.Engine(engine_config())
    module = wasmtime.Module.from_file(engine, str(wasm))
    target.write_bytes(module.serialize())


def safe_extract(archive: Path, target: Path) -> None:
    """Unpack regular files only; refuse absolute paths, drives, and `..`."""
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = PurePosixPath(member.filename)
            if (name.is_absolute() or ".." in name.parts or ":" in member.filename
                    or "\\" in member.filename):
                raise SetupError(f"Unsafe path in runtime archive: {member.filename!r}")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise SetupError(f"Symbolic link in runtime archive: {member.filename!r}")
        bundle.extractall(target)


def setup(
    paths: RuntimePaths,
    runtime: PythonRuntime = PYTHON,
    *,
    fetch: Downloader = download,
    compile_wasm: Compiler = compile_module,
) -> dict[str, Any]:
    paths.home.mkdir(parents=True, exist_ok=True)
    downloaded = False
    if not paths.archive.exists() or _sha256(paths.archive) != runtime.zip_sha256:
        partial = paths.archive.with_suffix(".partial")
        fetch(runtime.url, partial)
        actual = _sha256(partial)
        if actual != runtime.zip_sha256:
            partial.unlink(missing_ok=True)
            raise SetupError(
                f"Downloaded runtime checksum {actual} does not match the pinned "
                f"{runtime.zip_sha256}; nothing was installed")
        partial.replace(paths.archive)
        downloaded = True

    with zipfile.ZipFile(paths.archive) as bundle:
        try:
            archived_wasm = hashlib.sha256(bundle.read("python.wasm")).hexdigest()
        except KeyError:
            raise SetupError("Runtime archive does not contain python.wasm") from None
    reused = (paths.wasm.is_file() and paths.lib.is_dir()
              and sha256_file(paths.wasm) == archived_wasm)
    if not reused:
        # Unpack beside the old copy, then swap, so a failure leaves nothing half-written.
        unpacked = paths.home / "runtime.new"
        shutil.rmtree(unpacked, ignore_errors=True)
        safe_extract(paths.archive, unpacked)
        if not (unpacked / "python.wasm").is_file() or not (unpacked / "lib").is_dir():
            shutil.rmtree(unpacked, ignore_errors=True)
            raise SetupError("Runtime archive does not contain python.wasm and lib/")
        shutil.rmtree(paths.root, ignore_errors=True)
        unpacked.replace(paths.root)

    paths.compiled.unlink(missing_ok=True)
    compile_wasm(paths.wasm, paths.compiled)
    manifest = {
        "runtime": f"{runtime.name}-{runtime.version}",
        "source": runtime.url,
        "zip_sha256": runtime.zip_sha256,
        "python_wasm_sha256": sha256_file(paths.wasm),
        "compiled": paths.compiled.name,
        "compiled_sha256": sha256_file(paths.compiled),
        "wasmtime": WASMTIME_VERSION,
    }
    paths.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"home": str(paths.home), "downloaded": downloaded,
            "reused_unpacked_runtime": reused, **manifest}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
