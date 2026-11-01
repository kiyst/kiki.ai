"""Gate for the llama.cpp plan: does the trained adapter work on the 4-bit QAT Gemma?

Starts llama.cpp's server twice on 127.0.0.1 (plain Gemma, then Gemma with the
adapter loaded but switched off by default) and checks:

1. Template: llama.cpp's prompt for each conversation equals the training
   format (Google's template, thinking off).
2. Off = plain: with the adapter at scale 0, next-token probabilities match
   plain Gemma.
3. On changes it: at scale 1, probabilities move.

Prints a short greedy reply with the adapter off and on for a human to read.
Exit code 0 only if all checks pass. Writes adapter_check.json next to the adapter.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from train_unsloth import load_rows, make_render  # noqa: E402

PORT = 8090
TOLERANCE = 1e-3


def post(path: str, body: dict) -> dict:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def start(server: Path, model: Path, lora: Path | None, gpu_layers: int) -> subprocess.Popen:
    command = [str(server), "-m", str(model), "--host", "127.0.0.1", "--port", str(PORT),
               "-c", "4096", "-ngl", str(gpu_layers), "--jinja", "--seed", "1"]
    if lora:
        command += ["--lora", str(lora), "--lora-init-without-apply"]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(600):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as response:
                if response.status == 200:
                    return process
        except OSError:
            time.sleep(1)
    process.kill()
    raise SystemExit("llama-server did not start")


def top_probs(response: dict) -> dict[str, float]:
    """Next-token probabilities, across llama.cpp's response formats."""
    import math
    first = response["completion_probabilities"][0]
    if "top_logprobs" in first:
        return {item["token"]: math.exp(item["logprob"]) for item in first["top_logprobs"]}
    if "top_probs" in first:
        return {item["token"]: item["prob"] for item in first["top_probs"]}
    return {item["tok_str"]: item["prob"] for item in first["probs"]}


def difference(a: dict[str, float], b: dict[str, float]) -> float:
    return max(abs(a.get(token, 0.0) - b.get(token, 0.0)) for token in set(a) | set(b))


def probe(prompt: str, lora_scale: float | None) -> dict[str, float]:
    body = {"prompt": prompt, "n_predict": 1, "n_probs": 10, "temperature": 0, "cache_prompt": False}
    if lora_scale is not None:
        body["lora"] = [{"id": 0, "scale": lora_scale}]
    return top_probs(post("/completion", body))


def reply(prompt: str, lora_scale: float | None) -> str:
    body = {"prompt": prompt, "n_predict": 60, "temperature": 0, "cache_prompt": False}
    if lora_scale is not None:
        body["lora"] = [{"id": 0, "scale": lora_scale}]
    return post("/completion", body)["content"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True, help="llama-server binary")
    parser.add_argument("--model", type=Path, required=True, help="Q4_0 GGUF of the QAT base")
    parser.add_argument("--lora", type=Path, required=True, help="adapter converted to GGUF")
    parser.add_argument("--base-dir", type=Path, required=True, help="the base model's Hugging Face folder")
    parser.add_argument("--dataset", type=Path, default=HERE / "smoke_conversations.jsonl")
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from transformers import AutoProcessor
    render = make_render(AutoProcessor.from_pretrained(args.base_dir))
    conversations = [row["messages"][:-1] for row in load_rows(args.dataset)[:3]]
    prompts = [render(messages, True) for messages in conversations]
    failures, results = [], {"template": [], "probabilities": []}

    server = start(args.server, args.model, None, args.gpu_layers)
    try:
        for messages, expected in zip(conversations, prompts):
            got = post("/apply-template", {"messages": messages})["prompt"]
            same = got == expected
            bos_only = not same and got.removeprefix("<bos>") == expected.removeprefix("<bos>")
            results["template"].append({"identical": same, "differs_only_in_leading_bos": bos_only})
            if not same and not bos_only:
                failures.append(f"template differs: llama.cpp {got[-120:]!r} vs training {expected[-120:]!r}")
        plain = [probe(prompt, None) for prompt in prompts]
    finally:
        server.kill()
        server.wait()

    server = start(args.server, args.model, args.lora, args.gpu_layers)
    try:
        off = [probe(prompt, 0.0) for prompt in prompts]
        on = [probe(prompt, 1.0) for prompt in prompts]
        sample = {"off": reply(prompts[0], 0.0), "on": reply(prompts[0], 1.0)}
    finally:
        server.kill()
        server.wait()

    for number, (p, f, n) in enumerate(zip(plain, off, on), 1):
        row = {"off_vs_plain": round(difference(p, f), 5), "on_vs_off": round(difference(f, n), 5)}
        results["probabilities"].append(row)
        if row["off_vs_plain"] > TOLERANCE:
            failures.append(f"prompt {number}: adapter off does not match plain Gemma ({row['off_vs_plain']})")
    if all(row["on_vs_off"] <= TOLERANCE for row in results["probabilities"]):
        failures.append("adapter on changes nothing")
    results.update({"sample_reply": sample, "failures": failures, "passed": not failures})
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
