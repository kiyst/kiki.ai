"""Coding benchmarks for Kiki, graded inside the WebAssembly sandbox.

Benchmarks (downloaded to %LOCALAPPDATA%\\kiki\\benchmarks, not vendored):

- HumanEval+ and MBPP+ from EvalPlus (Apache-2.0): reports the original base
  tests and the stricter "+" tests. Prompts use EvalPlus's instruction text.
  Grading follows EvalPlus: expected outputs come from the canonical solution,
  floats use atol/rtol, and its special oracles are reproduced.
- LeetCodeDataset test split (newfacade, Apache-2.0): Medium and Hard
  problems released August 2024 to March 2025, with the dataset's own prompt
  and hidden `check` tests.

The model sees only the problem prompt. Tests, inputs, and canonical solutions
are written only into the grading run's staging directory.

Usage (Kiki's virtual environment, from this folder, Ollama running):

    python coding_benchmark.py humaneval [--style kiki|bare] [--limit N]
    python coding_benchmark.py mbpp
    python coding_benchmark.py leetcode
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

from evalplus_mbpp import mbpp_deserialize_inputs
from wasm_trial import run

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from kiki.model_client import CHAT_SYSTEM_PROMPT  # noqa: E402
from kiki.personality import PersonalitySettings, personality_prompt  # noqa: E402

DATA = Path(os.environ["LOCALAPPDATA"]) / "kiki" / "benchmarks"
RESULTS = ROOT / "evals" / "results" / "coding-benchmarks"
RECEIPTS = ROOT / "evals" / "receipts" / "coding-benchmarks"
MODEL = "qwen3:4b-instruct"
OPTIONS = {"num_ctx": 4096, "temperature": 0}
THINK = False  # Kiki runs with thinking off; --think measures what thinking buys
GRADE_TIMEOUT = float(os.environ.get("KIKI_BENCH_TIMEOUT", "60"))
GRADE_MEMORY_MIB = int(os.environ.get("KIKI_BENCH_MEMORY_MIB", "512"))
GRADE_JOB_MIB = GRADE_MEMORY_MIB + 512

EVALPLUS_INSTRUCTION = (
    "Please provide a self-contained Python script that solves the following "
    "problem in a markdown code block:\n```\n{prompt}\n```\n"
)

SET_EQ = ["similar_elements", "find_char_long", "common_in_nested_lists", "extract_singly",
          "larg_nnum", "intersection_array", "find_dissimilar", "Diff"]
NOT_NONE = ["check_str", "text_match_three", "text_starta_endb"]

EVALPLUS_GRADER = r'''
import copy, io, json, math, sys
inf = float("inf"); nan = float("nan")
RESULT = {}
def emit():
    sys.stdout = sys.__stdout__
    print("\n__RESULT__ " + json.dumps(RESULT))
DATASET, ENTRY, ATOL = %(dataset)r, %(entry)r, %(atol)r
SET_EQ, NOT_NONE = %(set_eq)r, %(not_none)r
BASE = %(base)s
PLUS = %(plus)s
ref_ns = {}
exec(compile(%(reference)r, "reference", "exec"), ref_ns)
ref = ref_ns[ENTRY]
expected = {"base": [ref(*copy.deepcopy(a)) for a in BASE], "plus": [ref(*copy.deepcopy(a)) for a in PLUS]}

def _poly(xs, x):
    return sum(c * math.pow(x, i) for i, c in enumerate(xs))
def _surface_area(base_edge, height):
    slant = math.sqrt((base_edge / 2) ** 2 + height ** 2)
    return round(base_edge ** 2 + 4 * (base_edge * slant) / 2)
def _digit_distance(a, b):
    a, b = str(a), str(b); n = max(len(a), len(b)); a, b = a.zfill(n), b.zfill(n)
    return sum(abs(int(x) - int(y)) for x, y in zip(a, b))
def is_floats(x):
    if isinstance(x, float):
        return True
    return isinstance(x, (list, tuple)) and bool(x) and all(isinstance(i, float) for i in x)
def close(out, exp, atol):
    if isinstance(exp, (list, tuple)):
        return all(close(o, e, atol) for o, e in zip(out, exp))
    return abs(out - exp) <= atol + 1e-07 * abs(exp)
def passes(inp, out, exp):
    atol = ATOL
    exact = out == exp
    if DATASET == "mbpp":
        if ENTRY == "are_equivalent":
            exact = True
        elif ENTRY == "sum_div":
            exact = exact or out == 0
        elif ENTRY == "surface_Area":
            exact = exact or abs(out - _surface_area(*inp)) <= atol
        elif ENTRY == "digit_distance_nums":
            exact = exact or out == _digit_distance(*inp)
        elif ENTRY in SET_EQ:
            exact = set(out) == set(exp)
        elif ENTRY in NOT_NONE:
            # EvalPlus stores these expected outputs as "is not None" booleans.
            exp = exp if isinstance(exp, bool) else exp is not None
            exact = out == exp if isinstance(out, bool) else exp == (out is not None)
    if DATASET == "humaneval" and ENTRY == "find_zero":
        return abs(_poly(*inp, out)) <= atol
    if atol == 0 and is_floats(exp):
        atol = 1e-6
    if not exact and atol != 0:
        if type(out) != type(exp):
            return False
        if isinstance(exp, (list, tuple)) and len(out) != len(exp):
            return False
        return close(out, exp, atol)
    return exact

sys.stdout = io.StringIO()
try:
    cand_ns = {}
    exec(compile(%(candidate)r, "candidate", "exec"), cand_ns)
    cand = cand_ns[ENTRY]
except BaseException as error:
    RESULT.update(base=False, plus=False, error="load: " + repr(error)[:200])
    emit(); raise SystemExit(0)
for name in ("base", "plus"):
    ok = True
    for i, (inp, exp) in enumerate(zip(BASE if name == "base" else PLUS, expected[name])):
        sys.stdout = io.StringIO()
        try:
            out = cand(*copy.deepcopy(inp))
            good = passes(inp, out, exp)
        except BaseException as error:
            good = False
            RESULT["error"] = f"{name}[{i}]: " + repr(error)[:200]
        if not good:
            ok = False
            RESULT.setdefault("error", f"{name}[{i}]: wrong answer")
            break
    RESULT[name] = ok
    if not ok:
        RESULT.setdefault("plus", False)
        break
emit()
'''

LEETCODE_GRADER = r'''
import io, json, sys
RESULT = {}
def emit():
    sys.stdout = sys.__stdout__
    print("\n__RESULT__ " + json.dumps(RESULT))
sys.stdout = io.StringIO()
ns = {}
try:
    exec(compile(%(header)r + "\n" + %(candidate)r, "candidate", "exec"), ns)
    exec(compile(%(test)r, "tests", "exec"), ns)
    candidate = eval(%(entry)r, ns)
except BaseException as error:
    RESULT.update(passed=False, error="load: " + repr(error)[:200])
    emit(); raise SystemExit(0)
try:
    ns["check"](candidate)
    RESULT["passed"] = True
except AssertionError:
    RESULT.update(passed=False, error="wrong answer")
except BaseException as error:
    RESULT.update(passed=False, error=repr(error)[:200])
emit()
'''


MIN_HEADROOM_GB = 1.0
UNLOAD_EVERY = 40


def commit_headroom_gb() -> float:
    """Virtual-memory commit still available (Windows), in GB."""
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.ullAvailPageFile / 2**30


def unvalidated(benchmark: str) -> set[str]:
    """Problems whose reference solution does not pass in this sandbox."""
    path = RECEIPTS / "reference-selftest.json"
    if not path.exists():
        return set()
    report = json.loads(path.read_text(encoding="utf-8"))
    return {failure["id"] for failure in report.get(benchmark, {}).get("failures", [])}


def load(benchmark: str) -> list[dict]:
    if benchmark == "humaneval":
        with gzip.open(DATA / "HumanEvalPlus.jsonl.gz", "rt", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]
    if benchmark == "mbpp":
        with gzip.open(DATA / "MbppPlus.jsonl.gz", "rt", encoding="utf-8") as handle:
            problems = [json.loads(line) for line in handle]
        for problem in problems:
            for key in ("base_input", "plus_input"):
                problem[key] = mbpp_deserialize_inputs(problem["task_id"], problem[key])
        return problems
    rows = [json.loads(line) for line in open(DATA / "LeetCodeDataset-test.jsonl", encoding="utf-8")]
    return [row for row in rows if row["difficulty"] in ("Medium", "Hard")]


def problem_id(benchmark: str, problem: dict) -> str:
    return problem["task_id"]


def user_prompt(benchmark: str, problem: dict) -> str:
    if benchmark in ("humaneval", "mbpp"):
        return EVALPLUS_INSTRUCTION.format(prompt=problem["prompt"].strip())
    return problem["query"]


def system_prompt(style: str) -> str | None:
    if style == "bare":
        return None
    return f"{CHAT_SYSTEM_PROMPT}\n\n{personality_prompt(PersonalitySettings())}"


def generate(client: httpx.Client, style: str, prompt: str) -> dict:
    messages = []
    system = system_prompt(style)
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    started = time.perf_counter()
    response = client.post("/api/chat", json={
        "model": MODEL, "messages": messages, "stream": False, "think": THINK, "options": OPTIONS})
    response.raise_for_status()
    body = response.json()
    return {
        "answer": body["message"]["content"],
        "done_reason": body.get("done_reason"),
        "eval_count": body.get("eval_count"),
        "generate_s": round(time.perf_counter() - started, 2),
    }


FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.DOTALL)


def extract_code(answer: str, entry: str) -> str | None:
    """Pick the last Python block that defines the entry point; else the longest block."""
    blocks = [body for language, body in FENCE.findall(answer)
              if language.lower() in ("", "python", "py", "python3")]
    if not blocks:
        return None
    name = entry.split(".")[-1].split("(")[0] if "." in entry else entry
    defining = [b for b in blocks if re.search(rf"def\s+{re.escape(name)}\s*\(", b)]
    return (defining or sorted(blocks, key=len))[-1]


def prompt_header(prompt: str) -> str:
    """Import lines that precede the first def in a HumanEval prompt."""
    lines = []
    for line in prompt.splitlines():
        if line.startswith("def "):
            break
        if line.startswith(("import ", "from ")):
            lines.append(line)
    return "\n".join(lines)


def grader(benchmark: str, problem: dict, code: str) -> str:
    if benchmark in ("humaneval", "mbpp"):
        if benchmark == "humaneval":
            reference = problem["prompt"] + problem["canonical_solution"]
            candidate = prompt_header(problem["prompt"]) + "\n" + code
        else:
            reference = problem["canonical_solution"]
            candidate = code
        return EVALPLUS_GRADER % {
            "dataset": benchmark, "entry": problem["entry_point"], "atol": problem["atol"] or 0,
            "set_eq": SET_EQ, "not_none": NOT_NONE,
            "base": repr(problem["base_input"]), "plus": repr(problem["plus_input"]),
            "reference": reference, "candidate": candidate,
        }
    return LEETCODE_GRADER % {
        "header": problem["prompt"], "candidate": code,
        "test": problem["test"], "entry": problem["entry_point"],
    }


def grade(benchmark: str, problem: dict, code: str | None) -> dict:
    if code is None:
        return {"passed": False, "base": False, "plus": False, "error": "no code block"}
    result = run(grader(benchmark, problem, code), GRADE_TIMEOUT, GRADE_MEMORY_MIB, GRADE_JOB_MIB)
    marker = [line for line in (result.get("stdout") or "").splitlines() if line.startswith("__RESULT__ ")]
    outcome = json.loads(marker[-1][len("__RESULT__ "):]) if marker else {}
    if not marker:
        reason = "timed out" if result.get("timed_out") else (result.get("trap") or (result.get("stderr") or "")[-200:] or "no result")
        outcome = {"passed": False, "base": False, "plus": False, "error": f"sandbox: {reason}"}
    if benchmark != "leetcode":
        outcome.setdefault("plus", False)
        outcome["passed"] = bool(outcome.get("base")) and bool(outcome.get("plus"))
    outcome.update({"grade_s": result.get("wall_s"), "timed_out": result.get("timed_out", False),
                    "peak_mb": result.get("peak_job_mb")})
    return outcome


def summarize(benchmark: str, rows: list[dict]) -> dict:
    def rate(items: list[dict], key: str) -> dict:
        passed = sum(1 for r in items if r["grade"].get(key))
        return {"passed": passed, "total": len(items), "pct": round(100 * passed / max(len(items), 1), 1)}

    summary: dict = {"problems": len(rows)}
    excluded = unvalidated(benchmark)
    validated = [r for r in rows if r["id"] not in excluded]
    if benchmark == "leetcode":
        summary["overall"] = rate(rows, "passed")
        for level in ("Medium", "Hard"):
            summary[level.lower()] = rate([r for r in rows if r["difficulty"] == level], "passed")
            summary[f"{level.lower()}_validated"] = rate(
                [r for r in validated if r["difficulty"] == level], "passed")
        summary["overall_validated"] = rate(validated, "passed")
    else:
        summary["base"] = rate(rows, "base")
        summary["plus"] = rate(rows, "passed")
        summary["base_validated"] = rate(validated, "base")
        summary["plus_validated"] = rate(validated, "passed")
    summary["reference_failures_excluded_from_validated"] = sorted(excluded)
    summary["no_code"] = sum(1 for r in rows if r["grade"].get("error") == "no code block")
    summary["truncated"] = sum(1 for r in rows if r["generation"].get("done_reason") == "length")
    summary["grade_timeouts"] = sum(1 for r in rows if r["grade"].get("timed_out"))
    summary["mean_generate_s"] = round(sum(r["generation"]["generate_s"] for r in rows) / max(len(rows), 1), 1)
    summary["mean_grade_s"] = round(sum(r["grade"].get("grade_s") or 0 for r in rows) / max(len(rows), 1), 2)
    summary["max_grade_peak_mb"] = max((r["grade"].get("peak_mb") or 0 for r in rows), default=0)
    return summary


def main() -> None:
    global MODEL
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", choices=["humaneval", "mbpp", "leetcode"])
    parser.add_argument("--style", choices=["kiki", "bare"], default="kiki")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=MODEL, help="Ollama model (results kept per model)")
    parser.add_argument("--think", action="store_true", help="Let a hybrid model think first")
    parser.add_argument("--num-ctx", type=int, default=OPTIONS["num_ctx"])
    arguments = parser.parse_args()
    MODEL = arguments.model
    global THINK
    THINK = arguments.think
    OPTIONS["num_ctx"] = arguments.num_ctx

    problems = load(arguments.benchmark)[: arguments.limit]
    RESULTS.mkdir(parents=True, exist_ok=True)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    name = f"{arguments.benchmark}-{arguments.style}"
    if MODEL != "qwen3:4b-instruct":
        # Saved answers resume by name, so another model must not reuse them.
        name += "-" + re.sub(r"[^A-Za-z0-9.]+", "-", MODEL).strip("-")
    if THINK:
        name += "-think"
    log_path = RESULTS / f"{name}.jsonl"
    done = {}
    if log_path.exists():
        for line in open(log_path, encoding="utf-8"):
            row = json.loads(line)
            done[row["id"]] = row
    rows = []
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=600) as client, \
            open(log_path, "a", encoding="utf-8") as log:
        for number, problem in enumerate(problems, 1):
            identifier = problem_id(arguments.benchmark, problem)
            if identifier in done:
                rows.append(done[identifier])
                continue
            generated = sum(1 for r in rows if r["id"] not in done)
            if generated and generated % UNLOAD_EVERY == 0:
                # Ollama 0.40.12's runner leaks ~35 MB of commit per request
                # (4.4 GB -> 11.3 GB over ~250 requests); unloading resets it.
                client.post("/api/generate", json={"model": MODEL, "keep_alive": 0})
            headroom = commit_headroom_gb()
            if headroom < MIN_HEADROOM_GB:
                print(f"STOPPED: only {headroom:.1f} GB of commit headroom left "
                      f"(minimum {MIN_HEADROOM_GB}). Close some applications and rerun; "
                      "finished problems are kept.", flush=True)
                break
            prompt = user_prompt(arguments.benchmark, problem)
            generation = generate(client, arguments.style, prompt)
            entry = problem["entry_point"]
            code = extract_code(generation["answer"], entry)
            outcome = grade(arguments.benchmark, problem, code)
            row = {"id": identifier, "difficulty": problem.get("difficulty"),
                   "generation": generation, "code": code, "grade": outcome}
            rows.append(row)
            log.write(json.dumps(row) + "\n")
            log.flush()
            status = "PASS" if outcome.get("passed") else f"fail ({outcome.get('error', '')[:60]})"
            print(f"[{number}/{len(problems)}] {identifier}: {status} "
                  f"gen {generation['generate_s']}s grade {outcome.get('grade_s')}s", flush=True)

    if not rows:
        print("No problems finished; receipt not written.", flush=True)
        sys.exit(2)
    summary = summarize(arguments.benchmark, rows)
    summary["complete"] = len(rows) == len(problems)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()
    tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=30).json().get("models", [])
    digest = next((m["digest"][:12] for m in tags if m["name"] == MODEL), None)
    receipt = {
        "benchmark": arguments.benchmark, "style": arguments.style, "date": time.strftime("%Y-%m-%d"),
        "git_commit": commit, "model": MODEL, "model_digest": digest, "options": OPTIONS,
        "sandbox": f"wasmtime 50.0.1 + CPython 3.14.9 WASI, {GRADE_MEMORY_MIB} MiB guest, {GRADE_TIMEOUT:.0f} s per problem, 2 MiB wasm stack",
        "summary": summary,
        "per_problem": {r["id"]: r["grade"].get("passed") for r in rows},
    }
    (RECEIPTS / f"{name}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
