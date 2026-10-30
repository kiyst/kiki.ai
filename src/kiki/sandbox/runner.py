"""Run Python files in the sandbox and report what happened.

The only inputs are file names and texts held in memory. The worker command
line, the folders the guest can see, and the limits are all fixed here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..resilience import ErrorCode, KikiError
from . import jobs, preflight, staging
from .jobs import Job
from .limits import RunLimits
from .runtime import RuntimePaths, default_home

# One run at a time per Kiki process: the PC's memory is the binding limit.
_LOCK = threading.Lock()
BACKSTOP_S = 15.0
# Room left for everything else after a worst-case run.
SAFETY_MARGIN_MB = 512


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    memory_exceeded: bool = False
    output_truncated: bool = False
    output_killed: bool = False
    crashed: str | None = None
    duration_s: float = 0.0
    peak_memory_mb: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not (self.timed_out or self.output_killed or self.crashed)

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "ok": self.ok}


class SandboxRunner:
    def __init__(self, home: Path | None = None, limits: RunLimits | None = None) -> None:
        self.paths = RuntimePaths(home or default_home())
        self.limits = limits or RunLimits()
        staging.sweep()

    def run(self, files: Mapping[str, str], entry: str = "main.py",
            limits: RunLimits | None = None) -> RunResult:
        limits = limits or self.limits
        staging.validate(files, entry, limits)
        manifest = preflight.require(self.paths)
        headroom = jobs.commit_headroom_mb()
        needed = limits.worker_memory_mib + SAFETY_MARGIN_MB
        if headroom is not None and headroom < needed:
            raise KikiError(
                f"Not enough free memory to run code safely: {headroom / 1024:.1f} GB "
                f"available, {needed / 1024:.1f} GB needed. Close some applications "
                "and try again.",
                code=ErrorCode.SERVICE_UNAVAILABLE,
                retryable=True,
            )
        with _LOCK:
            folder = staging.stage(files, entry, limits)
            try:
                return self._execute(folder, manifest, limits)
            finally:
                staging.remove(folder)

    def _execute(self, folder: Path, manifest: dict[str, Any], limits: RunLimits) -> RunResult:
        spec = {
            "compiled": str(self.paths.compiled),
            "compiled_sha256": manifest["compiled_sha256"],
            "lib": str(self.paths.lib),
            "packages": str(self.paths.packages),
            "staging": str(folder),
            "memory_bytes": limits.memory_mib * 2**20,
            "timeout_s": limits.timeout_s,
            "keep_stdout": limits.keep_stdout_bytes,
            "keep_stderr": limits.keep_stderr_bytes,
            "kill_output_bytes": limits.kill_output_bytes,
        }
        job = Job(limits.worker_memory_mib * 2**20)
        started = time.perf_counter()
        try:
            # Settings go over stdin, not a file in %TEMP% that could be edited
            # between writing and reading (audit L).
            process = job.start([sys.executable, "-I", "-m", "kiki.sandbox.worker", "-"], stdin=True)
            backstop = False
            try:
                out, err = process.communicate(json.dumps(spec).encode("utf-8"),
                                               timeout=limits.timeout_s + BACKSTOP_S)
            except subprocess.TimeoutExpired:
                process.kill()
                out, err = process.communicate()
                backstop = True
            peak = job.peak_mb()
        finally:
            job.close()
        duration = round(time.perf_counter() - started, 3)
        return interpret(out, err, process.returncode, backstop, duration, peak)


def interpret(out: bytes, err: bytes, returncode: int | None, backstop: bool,
              duration: float, peak: float) -> RunResult:
    """Turn the worker's report (or its absence) into a RunResult."""
    try:
        report = json.loads(out.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError, UnicodeDecodeError):
        reason = ("stopped after the time limit" if backstop
                  else f"sandbox worker failed (exit {returncode})")
        detail = err.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        return RunResult(None, "", detail[0][-300:], timed_out=backstop, crashed=reason,
                         duration_s=duration, peak_memory_mb=peak)
    if "refused" in report:
        return RunResult(None, "", "", crashed=f"refused: {report['refused']}",
                         duration_s=duration, peak_memory_mb=peak)
    stderr = report.get("stderr", "")
    exit_code = report.get("exit_code")
    trap = report.get("trap")
    memory = (exit_code not in (0, None) and "MemoryError" in stderr)
    crashed = None if report.get("timed_out") or report.get("output_killed") else trap
    return RunResult(
        exit_code=exit_code,
        stdout=report.get("stdout", ""),
        stderr=stderr,
        timed_out=bool(report.get("timed_out")),
        memory_exceeded=memory,
        output_truncated=bool(report.get("output_truncated")),
        output_killed=bool(report.get("output_killed")),
        crashed=crashed,
        duration_s=duration,
        peak_memory_mb=peak,
    )
