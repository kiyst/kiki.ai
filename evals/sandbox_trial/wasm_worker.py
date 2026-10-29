"""Trial worker: run one Python program inside wasmtime with the planned limits.

Usage: python -I wasm_worker.py <spec.json>
Prints one JSON line with the result.
"""

import errno
import json
import os
import sys
import threading
import time

import wasmtime as wt

WASM_STACK = 2 * 2**20
HOST_THREAD_STACK = 16 * 2**20


def _reason(error: Exception) -> str:
    """The `wasm trap: ...` cause if present, else the first line."""
    lines = str(error).splitlines()
    causes = [line.strip() for line in lines if line.strip().startswith("wasm trap:")]
    return causes[-1] if causes else lines[0]


def main() -> None:
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    started = time.perf_counter()

    config = wt.Config()
    config.epoch_interruption = True
    # functools.cache recursion goes through C frames; the 512 KiB default
    # traps at ~500 levels. 2 MiB (wasmtime's async-stack ceiling) allows
    # ~3,000. It needs a host thread with a larger native stack (below).
    config.max_wasm_stack = WASM_STACK
    engine = wt.Engine(config)
    cache = spec["cache"]
    compiled = os.path.exists(cache)
    if compiled:
        module = wt.Module.deserialize_file(engine, cache)
    else:
        module = wt.Module.from_file(engine, spec["wasm"])
        with open(cache, "wb") as handle:
            handle.write(module.serialize())
    loaded = time.perf_counter()

    linker = wt.Linker(engine)
    linker.define_wasi()
    store = wt.Store(engine)
    store.set_limits(memory_size=spec["memory_bytes"])

    keep = {"stdout": spec["keep_stdout"], "stderr": spec["keep_stderr"]}
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"bytes": 0}
    flags = {"output_truncated": False, "output_killed": False, "timed_out": False}

    def sink(name: str):
        def write(data: bytes) -> int:
            totals["bytes"] += len(data)
            room = keep[name] - len(captured[name])
            if room > 0:
                captured[name] += data[:room]
            if len(data) > max(room, 0):
                flags["output_truncated"] = True
            if totals["bytes"] > spec["kill_output_bytes"]:
                flags["output_killed"] = True
                store.set_epoch_deadline(0)
                engine.increment_epoch()
                return -errno.EIO
            return len(data)

        return write

    wasi = wt.WasiConfig()
    wasi.argv = ["python", "-I", "-B", "-X", "utf8", "/input/kiki_launcher.py"]
    wasi.env = [["PYTHONDONTWRITEBYTECODE", "1"], ["PYTHONUNBUFFERED", "1"]]
    wasi.preopen_dir(spec["lib"], "/lib", False)
    wasi.preopen_dir(spec["input"], "/input", False)
    wasi.stdout_custom = sink("stdout")
    wasi.stderr_custom = sink("stderr")
    store.set_wasi(wasi)

    store.set_epoch_deadline(1)
    done = threading.Event()

    def clock() -> None:
        # One epoch tick at the deadline; Windows sleep granularity makes
        # counting many small ticks drift.
        if not done.wait(spec["timeout"]):
            engine.increment_epoch()

    threading.Thread(target=clock, daemon=True).start()

    outcome = {"exit_code": None, "trap": None}
    run_started = time.perf_counter()

    def execute() -> None:
        try:
            instance = linker.instantiate(store, module)
            instance.exports(store)["_start"](store)
            outcome["exit_code"] = 0
        except wt.ExitTrap as error:
            outcome["exit_code"] = error.code
        except wt.Trap as error:
            outcome["trap"] = _reason(error)
            if "interrupt" in str(error) and not flags["output_killed"]:
                flags["timed_out"] = True
        except wt.WasmtimeError as error:
            outcome["trap"] = _reason(error)

    threading.stack_size(HOST_THREAD_STACK)
    runner = threading.Thread(target=execute)
    runner.start()
    runner.join()
    exit_code, trap = outcome["exit_code"], outcome["trap"]
    finished = time.perf_counter()
    done.set()

    print(json.dumps({
        "exit_code": exit_code,
        "trap": trap,
        **flags,
        "stdout": captured["stdout"].decode("utf-8", "replace"),
        "stderr": captured["stderr"].decode("utf-8", "replace")[-2000:],
        "output_bytes": totals["bytes"],
        "compiled_from_cache": compiled,
        "load_s": round(loaded - started, 3),
        "run_s": round(finished - run_started, 3),
    }))


if __name__ == "__main__":
    main()
