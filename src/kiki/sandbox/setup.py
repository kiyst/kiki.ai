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

from .runtime import PACKAGES, PYTHON, WASMTIME_VERSION, Package, PythonRuntime, RuntimePaths
from .wasi import engine_config, sha256_file, tree_sha256

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


def safe_extract(archive: Path, target: Path, prefix: str = "") -> None:
    """Unpack regular files only; refuse absolute paths, drives, and `..`.

    With `prefix`, only members under that folder are unpacked.
    """
    with zipfile.ZipFile(archive) as bundle:
        members = [m for m in bundle.infolist() if m.filename.startswith(prefix)]
        for member in members:
            name = PurePosixPath(member.filename)
            if (name.is_absolute() or ".." in name.parts or ":" in member.filename
                    or "\\" in member.filename):
                raise SetupError(f"Unsafe path in archive: {member.filename!r}")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise SetupError(f"Symbolic link in archive: {member.filename!r}")
        bundle.extractall(target, members=members)


def _fetch_verified(url: str, target: Path, sha256: str, fetch: Downloader) -> bool:
    """Ensure `target` holds the pinned file. Returns True if it was downloaded."""
    if target.exists() and _sha256(target) == sha256:
        return False
    partial = target.with_suffix(".partial")
    fetch(url, partial)
    actual = _sha256(partial)
    if actual != sha256:
        partial.unlink(missing_ok=True)
        raise SetupError(
            f"Downloaded {target.name} checksum {actual} does not match the pinned "
            f"{sha256}; nothing was installed")
    partial.replace(target)
    return True


def install_packages(paths: RuntimePaths, packages: tuple[Package, ...],
                     fetch: Downloader) -> dict[str, Any]:
    """Unpack each pinned wheel's own folder into a fresh read-only tree."""
    paths.wheels.mkdir(parents=True, exist_ok=True)
    fresh = paths.home / "packages.new"
    shutil.rmtree(fresh, ignore_errors=True)
    fresh.mkdir()
    installed = {}
    for package in packages:
        wheel = paths.wheels / package.url.rsplit("/", 1)[-1]
        _fetch_verified(package.url, wheel, package.wheel_sha256, fetch)
        safe_extract(wheel, fresh, prefix=f"{package.top_level}/")
        if not (fresh / package.top_level).is_dir():
            raise SetupError(f"{wheel.name} does not contain {package.top_level}/")
        installed[package.name] = {"version": package.version, "wheel_sha256": package.wheel_sha256}
    shutil.rmtree(paths.packages, ignore_errors=True)
    fresh.replace(paths.packages)
    return {"packages": installed, "packages_sha256": tree_sha256(paths.packages)}


def setup(
    paths: RuntimePaths,
    runtime: PythonRuntime = PYTHON,
    *,
    fetch: Downloader = download,
    compile_wasm: Compiler = compile_module,
    packages: tuple[Package, ...] = PACKAGES,
) -> dict[str, Any]:
    paths.home.mkdir(parents=True, exist_ok=True)
    downloaded = _fetch_verified(runtime.url, paths.archive, runtime.zip_sha256, fetch)

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
    package_report = install_packages(paths, packages, fetch)
    manifest = {
        "runtime": f"{runtime.name}-{runtime.version}",
        "source": runtime.url,
        "zip_sha256": runtime.zip_sha256,
        "python_wasm_sha256": sha256_file(paths.wasm),
        "compiled": paths.compiled.name,
        "compiled_sha256": sha256_file(paths.compiled),
        "wasmtime": WASMTIME_VERSION,
        **package_report,
    }
    paths.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"home": str(paths.home), "downloaded": downloaded,
            "reused_unpacked_runtime": reused, **manifest}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
