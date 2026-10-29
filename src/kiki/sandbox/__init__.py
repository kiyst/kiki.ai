"""Run Python in a WebAssembly sandbox (wasmtime + CPython for WASI).

Nothing here is reachable from chat yet. Execution is wired to `/run` only
after that checkpoint is approved; see docs/CODING_SANDBOX_HANDOFF.md.
"""

from .limits import RunLimits
from .runner import RunResult, SandboxRunner

__all__ = ["RunLimits", "RunResult", "SandboxRunner"]
