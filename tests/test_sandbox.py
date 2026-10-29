"""Sandbox tests.

Unit tests need no runtime. Integration tests run real programs in the
WebAssembly sandbox and are skipped unless `kiki sandbox setup` has run.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from kiki.resilience import ErrorCode, KikiError
from kiki.sandbox import RunLimits, SandboxRunner, preflight, staging
from kiki.sandbox.runner import interpret
from kiki.sandbox.runtime import Package, PythonRuntime, RuntimePaths, default_home
from kiki.sandbox.setup import SetupError, setup
from kiki.sandbox.wasi import grants
from kiki.sandbox.worker import OutputSink, run as worker_run, trap_reason

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "kiki" / "sandbox"


# --- limits and staging -------------------------------------------------------

def test_limits_validate_ranges() -> None:
    RunLimits()
    with pytest.raises(ValueError, match="timeout_s"):
        RunLimits(timeout_s=0)
    with pytest.raises(ValueError, match="worker_memory_mib"):
        RunLimits(memory_mib=512, worker_memory_mib=512)


@pytest.mark.parametrize("name", [
    "../evil.py", "a/b.py", "a\\b.py", "C:evil.py", ".hidden.py", "kiki_launcher.py", "x.", "",
])
def test_staging_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(staging.StagingError):
        staging.validate({name: "print(1)", "main.py": ""}, "main.py", RunLimits())


def test_staging_enforces_count_size_and_entry() -> None:
    limits = RunLimits(max_files=2, max_input_bytes=10)
    with pytest.raises(staging.StagingError, match="Too many files"):
        staging.validate({"a.py": "", "b.py": "", "c.py": ""}, "a.py", limits)
    with pytest.raises(staging.StagingError, match="too large"):
        staging.validate({"a.py": "x" * 11}, "a.py", limits)
    with pytest.raises(staging.StagingError, match="Entry point"):
        staging.validate({"a.txt": ""}, "a.txt", RunLimits())
    with pytest.raises(staging.StagingError, match="Nothing to run"):
        staging.validate({}, "main.py", RunLimits())


def test_stage_writes_files_and_launcher_then_removes() -> None:
    folder = staging.stage({"main.py": "print('hi')"}, "main.py", RunLimits())
    try:
        assert (folder / "main.py").read_text(encoding="utf-8") == "print('hi')"
        launcher = (folder / staging.LAUNCHER_NAME).read_text(encoding="utf-8")
        assert "'main.py'" in launcher and '["/input", "/packages"]' in launcher
    finally:
        staging.remove(folder)
    assert not folder.exists()


def test_sweep_skips_recent_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(staging.tempfile, "gettempdir", lambda: str(tmp_path))
    old, new = tmp_path / "kiki-run-old", tmp_path / "kiki-run-new"
    old.mkdir()
    new.mkdir()
    an_hour_ago = time.time() - 3600
    os.utime(old, (an_hour_ago, an_hour_ago))

    assert staging.sweep() == 1
    assert not old.exists() and new.exists()


# --- fixed configuration ------------------------------------------------------

def test_guest_sees_only_three_read_only_folders(tmp_path: Path) -> None:
    assert grants(tmp_path / "lib", tmp_path / "run", tmp_path / "pkg") == [
        (str(tmp_path / "lib"), "/lib", False),
        (str(tmp_path / "run"), "/input", False),
        (str(tmp_path / "pkg"), "/packages", False),
    ]


def test_no_shell_invocation_in_sandbox_package() -> None:
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                assert isinstance(node.value, ast.Constant) and node.value.value is False, path
            if isinstance(node, ast.Attribute) and node.attr in ("system", "popen"):
                pytest.fail(f"{path.name} uses os.{node.attr}")


# --- output handling and result interpretation --------------------------------

def test_output_sink_keeps_prefix_and_stops_past_kill_limit() -> None:
    stops: list[bool] = []
    sink = OutputSink({"stdout": 5, "stderr": 5}, kill_bytes=12, on_kill=lambda: stops.append(True))
    write = sink.writer("stdout")

    assert write(b"abc") == 3
    assert write(b"defgh") == 5
    assert sink.text("stdout") == "abcde" and sink.truncated
    assert write(b"12345") < 0
    assert sink.killed and stops == [True]


def test_trap_reason_prefers_the_cause() -> None:
    error = RuntimeError("error while executing\n  0: frame\nCaused by:\n    wasm trap: interrupt")
    assert trap_reason(error) == "wasm trap: interrupt"


def test_interpret_reports_limits_and_failures() -> None:
    def report(**fields: object) -> bytes:
        base = {"exit_code": 0, "trap": None, "timed_out": False, "output_truncated": False,
                "output_killed": False, "stdout": "", "stderr": ""}
        return json.dumps({**base, **fields}).encode()

    assert interpret(report(stdout="hi\n"), b"", 0, False, 0.3, 70).ok
    timed = interpret(report(exit_code=None, trap="wasm trap: interrupt", timed_out=True), b"", 0, False, 10, 70)
    assert timed.timed_out and not timed.ok and timed.crashed is None
    memory = interpret(report(exit_code=1, stderr="MemoryError"), b"", 0, False, 1, 300)
    assert memory.memory_exceeded and not memory.ok
    broken = interpret(b"not json", b"Traceback\nboom", 1, False, 1, 10)
    assert broken.crashed == "sandbox worker failed (exit 1)" and broken.stderr == "boom"
    refused = interpret(json.dumps({"refused": "checksum"}).encode(), b"", 0, False, 0.1, 10)
    assert refused.crashed == "refused: checksum"


def test_worker_refuses_a_tampered_compiled_runtime(tmp_path: Path) -> None:
    compiled = tmp_path / "python.compiled"
    compiled.write_bytes(b"not what setup produced")
    result = worker_run({"compiled": str(compiled), "compiled_sha256": "0" * 64})
    assert "refused" in result


# --- preflight and setup ------------------------------------------------------

def test_missing_runtime_fails_closed_with_the_fix(tmp_path: Path) -> None:
    with pytest.raises(KikiError) as caught:
        SandboxRunner(tmp_path).run({"main.py": "print(1)"})
    assert caught.value.code is ErrorCode.SERVICE_UNAVAILABLE
    assert "kiki sandbox setup" in str(caught.value)


def test_low_memory_refuses_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from kiki.sandbox import jobs, runner as runner_module

    monkeypatch.setattr(runner_module.preflight, "require", lambda paths: {})
    monkeypatch.setattr(jobs, "commit_headroom_mb", lambda: 300.0)
    with pytest.raises(KikiError, match="Not enough free memory") as caught:
        SandboxRunner().run({"main.py": "print(1)"})
    assert caught.value.retryable


def test_wrong_wasmtime_version_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.metadata, "version", lambda name: "1.0.0")
    check = next(c for c in preflight.checks(RuntimePaths(tmp_path)) if c.name == "wasmtime")
    assert not check.ok and "wasmtime==" in check.fix


def _fake_runtime(tmp_path: Path, members: dict[str, bytes]) -> tuple[PythonRuntime, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    data = buffer.getvalue()
    runtime = PythonRuntime("python-wasi", "3.14.9", "https://example.invalid/python.zip",
                            hashlib.sha256(data).hexdigest())
    return runtime, data


def _fetcher(data: bytes, extra: dict[str, bytes] | None = None):
    def fetch(url: str, target: Path) -> None:
        target.write_bytes((extra or {}).get(url, data))
    return fetch


def _fake_package() -> tuple[Package, bytes]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        wheel.writestr("sortedcontainers/__init__.py", "from .sortedlist import SortedList\n")
        wheel.writestr("sortedcontainers/sortedlist.py", "class SortedList(list):\n    pass\n")
        wheel.writestr("sortedcontainers-2.4.0.dist-info/METADATA", "Name: sortedcontainers")
    data = buffer.getvalue()
    url = "https://example.invalid/sortedcontainers-2.4.0-py2.py3-none-any.whl"
    return Package("sortedcontainers", "2.4.0", url, hashlib.sha256(data).hexdigest(),
                   "sortedcontainers"), data


def _fake_compile(wasm: Path, target: Path) -> None:
    target.write_bytes(b"compiled:" + wasm.read_bytes())


def test_setup_verifies_installs_and_satisfies_preflight(tmp_path: Path) -> None:
    runtime, data = _fake_runtime(tmp_path, {
        "python.wasm": b"\0asm fake", "lib/python3.14/os.py": b"", "LICENSE": b"PSF"})
    paths = RuntimePaths(tmp_path / "home")
    package, wheel = _fake_package()
    fetch = _fetcher(data, {package.url: wheel})

    report = setup(paths, runtime, fetch=fetch, compile_wasm=_fake_compile, packages=(package,))

    assert report["downloaded"] and not report["reused_unpacked_runtime"]
    assert report["packages"] == {"sortedcontainers": {"version": "2.4.0",
                                                       "wheel_sha256": package.wheel_sha256}}
    assert sorted(p.name for p in paths.packages.iterdir()) == ["sortedcontainers"]
    assert all(check.ok for check in preflight.checks(paths)), preflight.checks(paths)
    again = setup(paths, runtime, fetch=_fetcher(b"unused"), compile_wasm=_fake_compile,
                  packages=(package,))
    assert not again["downloaded"] and again["reused_unpacked_runtime"]

    (paths.packages / "sortedcontainers" / "sortedlist.py").write_text("import os  # changed")
    assert not next(c for c in preflight.checks(paths) if c.name == "packages").ok
    paths.compiled.write_bytes(b"tampered")
    assert not all(check.ok for check in preflight.checks(paths))


def test_setup_rejects_a_checksum_mismatch(tmp_path: Path) -> None:
    runtime, _ = _fake_runtime(tmp_path, {"python.wasm": b"x", "lib/a.py": b""})
    paths = RuntimePaths(tmp_path / "home")
    with pytest.raises(SetupError, match="does not match"):
        setup(paths, runtime, fetch=_fetcher(b"something else"), compile_wasm=_fake_compile,
              packages=())
    assert not paths.archive.exists() and not paths.root.exists()


def test_setup_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    runtime, data = _fake_runtime(tmp_path, {"python.wasm": b"x", "../escape.txt": b"!"})
    paths = RuntimePaths(tmp_path / "home")
    with pytest.raises(SetupError, match="Unsafe path"):
        setup(paths, runtime, fetch=_fetcher(data), compile_wasm=_fake_compile, packages=())
    assert not (tmp_path / "escape.txt").exists()


# --- integration: real programs in the sandbox ---------------------------------

def _installed() -> bool:
    try:
        preflight.require(RuntimePaths(default_home()))
        return True
    except KikiError:
        return False


integration = pytest.mark.skipif(not _installed(), reason="run `kiki sandbox setup` first")


@pytest.fixture
def runner() -> SandboxRunner:
    return _runner_or_skip()


def _runner_or_skip() -> SandboxRunner:
    """Real runs need memory headroom; a busy PC skips them instead of failing."""
    from kiki.sandbox import jobs
    from kiki.sandbox.runner import SAFETY_MARGIN_MB

    headroom = jobs.commit_headroom_mb()
    needed = RunLimits().worker_memory_mib + SAFETY_MARGIN_MB
    if headroom is not None and headroom < needed:
        pytest.skip(f"only {headroom:.0f} MB of memory headroom; {needed} MB needed")
    return SandboxRunner()


def _probe(*expressions: str) -> str:
    lines = ["import os, socket, subprocess"]
    for expression in expressions:
        lines += ["try:", f"    {expression}", f"    print('ALLOWED', {expression!r})",
                  "except BaseException as error:", "    print('blocked', type(error).__name__)"]
    return "\n".join(lines)


@integration
def test_runs_code_and_propagates_exit_codes(runner: SandboxRunner) -> None:
    result = runner.run({"main.py": "import helper\nprint(helper.twice(21))",
                         "helper.py": "def twice(n):\n    return n * 2\n"})
    assert result.ok and result.stdout.strip() == "42"
    failed = runner.run({"main.py": "import sys\nprint('bye')\nsys.exit(3)"})
    assert failed.exit_code == 3 and not failed.ok


@integration
def test_host_files_network_and_processes_are_blocked(runner: SandboxRunner) -> None:
    result = runner.run({"main.py": _probe(
        "open('C:/Windows/win.ini').read()",
        "os.listdir('/input/..')",
        "open('/input/new.txt', 'w').write('x')",
        "open('/tmp/x', 'w').write('x')",
        "socket.create_connection(('1.1.1.1', 53), timeout=2)",
        "subprocess.run(['cmd'])",
        "os.environ['PATH']",
    )})
    assert result.ok
    assert "ALLOWED" not in result.stdout and result.stdout.count("blocked") == 7


@integration
def test_time_memory_and_output_limits(runner: SandboxRunner) -> None:
    loop = runner.run({"main.py": "while True:\n    pass"}, limits=RunLimits(timeout_s=1.0))
    assert loop.timed_out and not loop.ok and loop.duration_s < 6

    bomb = runner.run({"main.py": "chunks = []\nwhile True:\n    chunks.append(bytearray(10 << 20))"})
    assert bomb.memory_exceeded and not bomb.ok and bomb.peak_memory_mb < 768

    flood = runner.run({"main.py": "while True:\n    print('x' * 1000)"})
    assert flood.output_killed and flood.output_truncated and len(flood.stdout) <= 64 * 1024


@integration
def test_allowlisted_package_imports_and_is_read_only(runner: SandboxRunner) -> None:
    code = _probe("open('/packages/sortedcontainers/x.py', 'w').write('x')") + (
        "\nfrom sortedcontainers import SortedList\nprint(list(SortedList([3, 1, 2])))")
    result = runner.run({"main.py": code})
    assert result.ok, result.stderr
    assert "blocked" in result.stdout and "[1, 2, 3]" in result.stdout


@integration
def test_memoized_recursion_reaches_a_thousand_levels(runner: SandboxRunner) -> None:
    code = ("import sys\nfrom functools import cache\nsys.setrecursionlimit(10**5)\n"
            "@cache\ndef depth(n):\n    return 0 if n == 0 else 1 + depth(n - 1)\nprint(depth(1000))")
    result = runner.run({"main.py": code})
    assert result.ok and result.stdout.strip() == "1000"


@integration
def test_staging_is_removed_after_every_run(runner: SandboxRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Path] = []
    original = staging.stage

    def recording(*args: object, **kwargs: object) -> Path:
        folder = original(*args, **kwargs)  # type: ignore[arg-type]
        created.append(folder)
        return folder

    monkeypatch.setattr(staging, "stage", recording)
    runner.run({"main.py": "print(1)"})
    runner.run({"main.py": "raise SystemExit(2)"})
    runner.run({"main.py": "while True: pass"}, limits=RunLimits(timeout_s=0.5))
    assert len(created) == 3
    assert not any(path.exists() or path.with_suffix(".json").exists() for path in created)
