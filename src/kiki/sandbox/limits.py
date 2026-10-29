"""Resource limits for one sandboxed run."""

from __future__ import annotations

from dataclasses import dataclass

KIB = 1024
MIB = 1024 * KIB


@dataclass(frozen=True)
class RunLimits:
    """Defaults are the values validated in the October 29 trial."""

    timeout_s: float = 10.0
    memory_mib: int = 256
    worker_memory_mib: int = 768
    keep_stdout_bytes: int = 64 * KIB
    keep_stderr_bytes: int = 16 * KIB
    kill_output_bytes: int = 1 * MIB
    max_files: int = 50
    max_input_bytes: int = 2 * MIB

    def __post_init__(self) -> None:
        _check("timeout_s", self.timeout_s, 0.5, 120)
        _check("memory_mib", self.memory_mib, 16, 1024)
        _check("worker_memory_mib", self.worker_memory_mib, self.memory_mib + 128, 2048)
        _check("keep_stdout_bytes", self.keep_stdout_bytes, 1, 1 * MIB)
        _check("keep_stderr_bytes", self.keep_stderr_bytes, 1, 1 * MIB)
        _check("kill_output_bytes", self.kill_output_bytes,
               self.keep_stdout_bytes + self.keep_stderr_bytes, 16 * MIB)
        _check("max_files", self.max_files, 1, 200)
        _check("max_input_bytes", self.max_input_bytes, 1, 16 * MIB)


def _check(name: str, value: float, low: float, high: float) -> None:
    if isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value!r}")
