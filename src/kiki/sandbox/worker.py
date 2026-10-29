"""Child process that runs one program inside wasmtime.

Started by `runner.py` as `python -I -m kiki.sandbox.worker <spec.json>`
inside a Job Object. Prints one JSON line with the result.
"""

from __future__ import annotations

import errno
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .wasi import GUEST_ARGV, GUEST_ENV, HOST_THREAD_STACK_BYTES, engine_config, grants, sha256_file


class OutputSink:
    """Keeps the first bytes of each stream; asks to stop past the kill limit."""

    def __init__(self, keep: dict[str, int], kill_bytes: int, on_kill: Callable[[], None]) -> None:
        self.keep = keep
        self.kill_bytes = kill_bytes
        self.on_kill = on_kill
        self.captured = {name: bytearray() for name in keep}
        self.total = 0
        self.truncated = False
        self.killed = False

    def writer(self, name: str) -> Callable[[bytes], int]:
        def write(data: bytes) -> int:
            self.total += len(data)
            buffer = self.captured[name]
            room = self.keep[name] - len(buffer)
            if room > 0:
                buffer += data[:room]
            if len(data) > max(room, 0):
                self.truncated = True
            if self.total > self.kill_bytes:
                if not self.killed:
                    self.killed = True
                    self.on_kill()
                return -errno.EIO
            return len(data)

        return write

    def text(self, name: str) -> str:
        return self.captured[name].decode("utf-8", "replace")


def trap_reason(error: Exception) -> str:
    """The `wasm trap: ...` cause if present, else the first line."""
    lines = str(error).splitlines() or [type(error).__name__]
    causes = [line.strip() for line in lines if line.strip().startswith("wasm trap:")]
    return causes[-1] if causes else lines[0]


def run(spec: dict[str, Any]) -> dict[str, Any]:
    import wasmtime as wt

    compiled = Path(spec["compiled"])
    if sha256_file(compiled) != spec["compiled_sha256"]:
        # Deserializing skips validation, so an altered cache must never load.
        return {"refused": "compiled runtime does not match its recorded checksum"}
    engine = wt.Engine(engine_config())
    module = wt.Module.deserialize_file(engine, str(compiled))

    linker = wt.Linker(engine)
    linker.define_wasi()
    store = wt.Store(engine)
    store.set_limits(memory_size=spec["memory_bytes"])

    def stop() -> None:
        store.set_epoch_deadline(0)
        engine.increment_epoch()

    sink = OutputSink({"stdout": spec["keep_stdout"], "stderr": spec["keep_stderr"]},
                      spec["kill_output_bytes"], stop)
    wasi = wt.WasiConfig()
    wasi.argv = GUEST_ARGV
    wasi.env = GUEST_ENV
    for host, guest, writable in grants(Path(spec["lib"]), Path(spec["staging"])):
        wasi.preopen_dir(host, guest, writable)
    wasi.stdout_custom = sink.writer("stdout")
    wasi.stderr_custom = sink.writer("stderr")
    store.set_wasi(wasi)

    # One epoch tick fired at the deadline. Counting many small ticks drifts
    # on Windows (a 10 s limit ran 15.4 s in the trial).
    store.set_epoch_deadline(1)
    finished = threading.Event()

    def clock() -> None:
        if not finished.wait(spec["timeout_s"]):
            engine.increment_epoch()

    threading.Thread(target=clock, daemon=True).start()
    outcome: dict[str, Any] = {"exit_code": None, "trap": None, "timed_out": False}

    def execute() -> None:
        try:
            instance = linker.instantiate(store, module)
            instance.exports(store)["_start"](store)
            outcome["exit_code"] = 0
        except wt.ExitTrap as error:
            outcome["exit_code"] = error.code
        except wt.Trap as error:
            outcome["trap"] = trap_reason(error)
            outcome["timed_out"] = "interrupt" in str(error) and not sink.killed
        except wt.WasmtimeError as error:
            outcome["trap"] = trap_reason(error)

    started = time.perf_counter()
    threading.stack_size(HOST_THREAD_STACK_BYTES)
    thread = threading.Thread(target=execute)
    thread.start()
    thread.join()
    finished.set()
    return {
        **outcome,
        "output_truncated": sink.truncated,
        "output_killed": sink.killed,
        "stdout": sink.text("stdout"),
        "stderr": sink.text("stderr"),
        "run_s": round(time.perf_counter() - started, 3),
    }


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(run(spec)))


if __name__ == "__main__":
    main()
