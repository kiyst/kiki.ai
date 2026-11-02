"""One configuration, two tests: prompt and sampling variants for Kiki's voice.

Runs a single arm (base Gemma or the adapter) with optional changes and writes
transcripts for comparison:
  --voice-section FILE  inserted right after the card in every system message
                        (a test of a Capri-style "in practice" section; not part
                        of the frozen contract)
  --temperature/--min-p sampling (top-k 64 and top-p 0.95 stay)
  --dry-multiplier      DRY repetition penalty, as in llama.cpp (base 1.75,
                        allowed length 2, last 1024 tokens, newline breaks)
  --trims               deterministic clean-up after the model: a repeated
                        interjection opener and stock closing questions

Tests: free-running safety probes (subset by --only, danger note on) and the
first --limit development conversations replayed from reference history.
Never touches the sealed holdout.

Usage (pod):
  python training/personality/eval_variants.py --name p2 --output ARTIFACTS/variants \
      --voice-section training/personality/eval/voice_in_practice.txt --temperature 0.8 --min-p 0.05 \
      --dry-multiplier 0.8 --only s01 s04 ... --limit 12 [--adapter ARTIFACTS/v2-pilot]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eval_v2_scripts import check, turns_of  # noqa: E402
from train_unsloth import BASE_MODEL, make_render  # noqa: E402
from v2_prompt import CARD, moment_message, system_message  # noqa: E402

OPENER = re.compile(r"^(?P<w>well|okay|ok|alright|ah|oh|so|right|look|fine|honestly|sure|yes|yeah|no)[,.!]\s+", re.I)
CLOSER = re.compile(r"(?<=[.!?])\s+[^.!?]*\b(anything else|what'?s next|what now|what'?s the plan|need anything)\b[^.!?]*\?\s*$",
                    re.I)


def trim(reply: str, earlier: list[str]) -> str:
    """Capri-style trims: a closing stock question, and an interjection opener already used."""
    out = CLOSER.sub("", reply).rstrip()
    found = OPENER.match(out)
    if found and any(OPENER.match(e) and OPENER.match(e).group("w").lower() == found.group("w").lower() for e in earlier):
        rest = out[found.end():]
        if len(rest.split()) >= 3:
            out = rest[0].upper() + rest[1:]
    return out if len(out.split()) >= 1 else reply


def dry_processor(multiplier: float, base: float = 1.75, allowed: int = 2, last_n: int = 1024, breakers=()):
    import torch
    from transformers import LogitsProcessor

    class Dry(LogitsProcessor):
        """For each earlier occurrence of the current suffix, penalise the token that followed it."""

        def __call__(self, input_ids, scores):
            ids = input_ids[0, -last_n:].tolist()
            n = len(ids)
            if n < 2:
                return scores
            last = ids[-1]
            penalties: dict[int, int] = {}
            for i in range(n - 2, -1, -1):
                if ids[i] != last:
                    continue
                length = 1
                while length <= i and ids[i - length] == ids[n - 1 - length] and ids[i - length] not in breakers:
                    length += 1
                follower = ids[i + 1]
                if follower in breakers:
                    continue
                if length > penalties.get(follower, 0):
                    penalties[follower] = length
            for token, length in penalties.items():
                if length >= allowed:
                    scores[0, token] -= multiplier * base ** (length - allowed)
            return scores

    return Dry()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, default=None, help="omit for base Gemma")
    parser.add_argument("--voice-section", type=Path, default=None)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--min-p", type=float, default=0.0)
    parser.add_argument("--dry-multiplier", type=float, default=0.0)
    parser.add_argument("--trims", action="store_true")
    parser.add_argument("--only", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--probes", type=Path, nargs="+",
                        default=[HERE / "eval" / "safety_probes.jsonl", HERE / "eval" / "safety_probes_means.jsonl"])
    parser.add_argument("--dataset", type=Path, default=HERE / "recovery" / "2026-11-01" / "prepared" / "development.jsonl")
    parser.add_argument("--seed", type=int, default=20261101)
    parser.add_argument("--max-new-tokens", type=int, default=400)
    args = parser.parse_args()
    out_dir = args.output / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    section = args.voice_section.read_text(encoding="utf-8").strip() if args.voice_section else ""

    def with_section(system: str) -> str:
        return system.replace(CARD, CARD + "\n\n" + section, 1) if section else system

    from unsloth import FastModel
    import torch
    from transformers import LogitsProcessorList

    model, processor = FastModel.from_pretrained(model_name=BASE_MODEL, max_seq_length=4096, load_in_4bit=True)
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(args.adapter))
    FastModel.for_inference(model)
    tokenizer = getattr(processor, "tokenizer", processor)
    render = make_render(processor)
    breakers = {t for t in tokenizer("\n", add_special_tokens=False)["input_ids"]}
    processors = LogitsProcessorList([dry_processor(args.dry_multiplier, breakers=breakers)]) if args.dry_multiplier else None

    def generate(messages: list[dict], seed: int) -> str:
        ids = tokenizer(render(messages, True), add_special_tokens=False, return_tensors="pt").to(model.device)
        torch.manual_seed(seed)
        options = dict(max_new_tokens=args.max_new_tokens, do_sample=True, temperature=args.temperature,
                       top_k=64, top_p=0.95, pad_token_id=tokenizer.pad_token_id or 0)
        if args.min_p:
            options["min_p"] = args.min_p
        if processors:
            options["logits_processor"] = processors
        with torch.no_grad():
            output = model.generate(**ids, **options)
        text = tokenizer.decode(output[0][ids["input_ids"].shape[1]:], skip_special_tokens=False)
        return text.split("<turn|>")[0].replace("<eos>", "").strip()

    load = lambda p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    probes = [s for p in args.probes for s in load(p) if not args.only or s["id"] in args.only]
    with (out_dir / "probes.jsonl").open("w", encoding="utf-8") as out:
        for script in probes:
            turns = turns_of(script, True)
            messages = [{"role": "system", "content": with_section(
                system_message(script.get("context") or {}, [t["user"] for t in turns]))}]
            replies: list[str] = []
            for number, turn in enumerate(turns, 1):
                messages += [{"role": "user", "content": turn["user"]},
                             {"role": "system", "content": moment_message(turn["moment"])}]
                reply = generate(messages, args.seed + number)
                if args.trims:
                    reply = trim(reply, replies)
                messages.append({"role": "assistant", "content": reply})
                replies.append(reply)
            checks = {c: check(c, replies) for c in script.get("expect", [])}
            out.write(json.dumps({"id": script["id"], "category": script["category"],
                                  "users": [t["user"] for t in turns], "replies": replies, "checks": checks},
                                 ensure_ascii=False) + "\n")
            print(f"probe {script['id']}", flush=True)

    records = load(args.dataset)[:args.limit]
    with (out_dir / "dev.jsonl").open("w", encoding="utf-8") as out:
        for number, record in enumerate(records, 1):
            messages = [dict(m) for m in record["messages"]]
            messages[0]["content"] = with_section(messages[0]["content"])
            earlier: list[str] = []
            turn = 0
            for index, message in enumerate(messages):
                if message["role"] != "assistant":
                    continue
                turn += 1
                reply = generate(messages[:index], args.seed + number * 100 + turn)
                if args.trims:
                    reply = trim(reply, earlier)
                earlier.append(reply)
                out.write(json.dumps({"id": record["id"], "turn": turn, "category": record["category"],
                                      "user": messages[index - 2]["content"], "reference": message["content"],
                                      "reply": reply}, ensure_ascii=False) + "\n")
            print(f"dev {record['id']}", flush=True)
    (out_dir / "config.json").write_text(json.dumps({"command": sys.argv, **{k: str(v) for k, v in vars(args).items()}},
                                                    indent=2) + "\n", encoding="utf-8")
    print("VARIANT-DONE", args.name)


if __name__ == "__main__":
    main()
