"""WebAssembly backend trial: latency, memory, and limit checks.

Run from this folder with Kiki's virtual environment (needs `wasmtime` and the
CPython WASI runtime under %LOCALAPPDATA%\\kiki\\wasi-python\\3.14.9):

    ..\\..\\.venv\\Scripts\\python.exe wasm_trial.py
"""

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from jobs import Job
from scenarios import SCENARIOS

HERE = Path(__file__).parent
RUNTIME = Path(os.environ["LOCALAPPDATA"]) / "kiki" / "wasi-python" / "3.14.9"
PYTHON = sys.executable
LAUNCHER = 'import runpy, sys\nsys.argv = ["main.py"]\nrunpy.run_path("/input/main.py", run_name="__main__")\n'


def run(code: str, timeout: float = 10.0, memory_mib: int = 256, job_mib: int = 768) -> dict:
    staging = Path(tempfile.mkdtemp(prefix="kiki-run-"))
    try:
        (staging / "main.py").write_text(code, encoding="utf-8")
        (staging / "kiki_launcher.py").write_text(LAUNCHER, encoding="utf-8")
        spec = {
            "wasm": str(RUNTIME / "runtime" / "python.wasm"),
            "lib": str(RUNTIME / "runtime" / "lib"),
            "cache": str(RUNTIME / "python.wasm.compiled"),
            "input": str(staging),
            "memory_bytes": memory_mib * 2**20,
            "timeout": timeout,
            "keep_stdout": 64 * 1024,
            "keep_stderr": 16 * 1024,
            "kill_output_bytes": 2**20,
        }
        spec_path = staging.with_suffix(".json")
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        job = Job(job_mib * 2**20)
        started = time.perf_counter()
        process = job.start([PYTHON, "-I", str(HERE / "wasm_worker.py"), str(spec_path)])
        killed = False
        try:
            out, err = process.communicate(timeout=timeout + 30)
        except subprocess.TimeoutExpired:
            process.kill()
            out, err = process.communicate()
            killed = True
        wall = time.perf_counter() - started
        peak = job.peak_mb()
        job.close()
        spec_path.unlink()
        try:
            result = json.loads(out.decode().strip().splitlines()[-1])
        except Exception:
            result = {"worker_failed": True, "worker_exit": process.returncode,
                      "worker_stderr": err.decode(errors="replace")[-800:]}
        result.update({"wall_s": round(wall, 3), "peak_job_mb": peak, "backstop_killed": killed})
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main() -> None:
    report = {"backend": "wasmtime", "runtime": "CPython 3.14.9 WASI", "results": {}}
    cache = RUNTIME / "python.wasm.compiled"
    if cache.exists():
        cache.unlink()
    report["cold_first_run"] = run(SCENARIOS["hello"])
    walls = [run(SCENARIOS["hello"])["wall_s"] for _ in range(10)]
    report["warm_hello_wall_s"] = {"median": statistics.median(walls), "min": min(walls), "max": max(walls)}
    for name, code in SCENARIOS.items():
        timeout = 10.0
        result = run(code, timeout)
        if name == "flood":
            result["stdout"] = result.get("stdout", "")[:80] + "..."
        report["results"][name] = result
        print(name, json.dumps({k: v for k, v in result.items() if k not in ("stdout", "stderr")}), flush=True)
        print("   stdout:", (result.get("stdout") or "")[:300].replace("\n", " | "))
        print("   stderr:", (result.get("stderr") or result.get("worker_stderr") or "")[-300:].replace("\n", " | "))
    computes = [run(SCENARIOS["compute"])["stdout"].split("compute_s=")[-1].strip() for _ in range(3)]
    report["compute_s_runs"] = computes
    native = subprocess.run([sys.executable, "-I", "-c", SCENARIOS["compute"]], capture_output=True, text=True)
    report["native_compute"] = native.stdout.strip()
    leftovers = [p.name for p in Path(tempfile.gettempdir()).glob("kiki-run-*")]
    report["leftover_staging"] = leftovers
    print("cold", report["cold_first_run"]["wall_s"], "load", report["cold_first_run"].get("load_s"))
    print("warm hello", report["warm_hello_wall_s"])
    print("compute wasm", computes, "native", report["native_compute"])
    print("leftovers", leftovers)
    (HERE.parent / "receipts" / "sandbox-trial" / "wasm-trial.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
