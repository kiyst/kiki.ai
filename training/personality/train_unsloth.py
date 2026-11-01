"""Train Kiki's v2 personality adapter on Gemma 4 E4B with Unsloth (QLoRA).

Before any training step, every example passes four checks; any failure stops
the run before paid GPU time is spent:

1. Format: the prompt the runtime will send for each of Kiki's replies is an
   exact prefix of the training text, with her reply directly after it
   (catches an empty thought block or any template difference).
2. Tokens: tokenizing that prompt alone gives the same tokens as the training
   text up to that point.
3. Mask: the trained text is exactly Kiki's replies plus the end-of-turn
   marker. A readable preview is written to mask_preview.txt.
4. Cache bug: the model's outputs with use_cache on and off agree (older
   Transformers gave garbage on Gemma 4 E4B with it off, which training uses).

--check-only runs checks 1-3 with the tokenizer alone (no GPU, no Unsloth).
--smoke trains 20 steps on a few examples so the adapter check can run.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gemma_format import (  # noqa: E402
    FormatError, expected_segments, preview, reply_spans, token_mask, trained_segments,
)

BASE_MODEL = "google/gemma-4-E4B-it-qat-q4_0-unquantized"
DEFAULT_DATASET = HERE / "recovery" / "2026-11-01" / "prepared" / "train_reviewed.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=HERE / "artifacts" / "v2-adapter")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--seed", type=int, default=20261101)
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=None,
                        help="default 1e-4; 2e-4 for --smoke so the adapter visibly changes outputs")
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--smoke", action="store_true", help="20 optimizer steps on a few examples")
    parser.add_argument("--check-only", action="store_true", help="format, token and mask checks only")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"line {number}: missing messages")
        rows.append({"id": record.get("id", f"line-{number}"), "messages": messages})
    if not rows:
        raise ValueError("dataset is empty")
    return rows


def make_render(processor):
    """The model's own chat template (Google's), thinking off: the format llama.cpp uses at runtime."""
    templater = processor if getattr(processor, "chat_template", None) else processor.tokenizer

    def render(messages: list[dict], add_generation_prompt: bool) -> str:
        options = dict(tokenize=False, add_generation_prompt=add_generation_prompt, enable_thinking=False)
        try:
            return templater.apply_chat_template(messages, **options)
        except (TypeError, ValueError, KeyError):
            # Some multimodal processors only accept content as a list of parts.
            parts = [{**m, "content": [{"type": "text", "text": m["content"]}]} for m in messages]
            return templater.apply_chat_template(parts, **options)
    return render


def build_examples(rows, render, tokenizer, max_length):
    """Checks 1-3. Returns (examples, report); raises SystemExit listing every failing example."""
    examples, problems, previews, lengths = [], [], [], []
    for row in rows:
        try:
            text, spans = reply_spans(render, row["messages"])
        except FormatError as error:
            problems.append(f"{row['id']}: format: {error}")
            continue
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
        for number, (start, _) in enumerate(spans, 1):
            prompt_ids = tokenizer(text[:start], add_special_tokens=False)["input_ids"]
            if ids[:len(prompt_ids)] != prompt_ids:
                problems.append(f"{row['id']}: tokens: reply {number}'s prompt tokenizes differently alone")
        mask, straddling = token_mask(offsets, spans)
        if straddling:
            problems.append(f"{row['id']}: mask: {straddling} token(s) straddle a reply edge")
        if trained_segments(text, offsets, mask) != expected_segments(row["messages"]):
            problems.append(f"{row['id']}: mask: trained text is not exactly Kiki's replies")
        if len(ids) > max_length:
            problems.append(f"{row['id']}: length: {len(ids)} tokens > {max_length}")
        lengths.append(len(ids))
        if len(previews) < 3:
            previews.append(f"===== {row['id']} =====\n{preview(text, offsets, mask)}\n")
        examples.append({
            "input_ids": ids,
            "labels": [token if trained else -100 for token, trained in zip(ids, mask)],
        })
    if problems:
        raise SystemExit("checks failed; nothing trained:\n  " + "\n  ".join(problems))
    report = {
        "examples": len(examples),
        "tokens": {"median": statistics.median(lengths), "max": max(lengths), "limit": max_length},
        "trained_token_share": round(
            sum(label != -100 for e in examples for label in e["labels"]) / sum(lengths), 3),
    }
    return examples, report, "\n".join(previews)


def cache_check(model, example) -> dict:
    """Check 4: outputs with use_cache on and off must agree."""
    import torch
    ids = torch.tensor([example["input_ids"][:512]], device=model.device)
    model.eval()
    with torch.no_grad():
        on = model(input_ids=ids, use_cache=True).logits.float()
        off = model(input_ids=ids, use_cache=False).logits.float()
    agreement = (on.argmax(-1) == off.argmax(-1)).float().mean().item()
    result = {"argmax_agreement": round(agreement, 4), "max_abs_diff": round((on - off).abs().max().item(), 3)}
    if agreement < 0.99:
        raise SystemExit(f"cache check failed (Gemma 4 use_cache bug?): {result}")
    return result


def lora_targets(model) -> dict:
    names = [name for name, _ in model.named_modules() if name.endswith("lora_A")]
    stray = [name for name in names if any(part in name for part in ("vision", "audio", "embed_vision", "embed_audio"))]
    if not names or stray:
        raise SystemExit(f"LoRA must cover language layers only; found {len(names)} modules, stray: {stray[:5]}")
    return {"lora_modules": len(names)}


def collate(pad_id):
    def collate_fn(batch):
        import torch
        width = max(len(item["input_ids"]) for item in batch)
        ids = [item["input_ids"] + [pad_id] * (width - len(item["input_ids"])) for item in batch]
        labels = [item["labels"] + [-100] * (width - len(item["labels"])) for item in batch]
        attention = [[1] * len(item["input_ids"]) + [0] * (width - len(item["input_ids"])) for item in batch]
        return {"input_ids": torch.tensor(ids), "labels": torch.tensor(labels),
                "attention_mask": torch.tensor(attention)}
    return collate_fn


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    rows = load_rows(args.dataset)
    if args.smoke:
        rows = rows[:8]
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "base_model": args.base_model,
        "dataset": args.dataset.name,
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "smoke": args.smoke,
        "python": platform.python_version(),
    }

    if args.check_only:
        from transformers import AutoProcessor
        processor = AutoProcessor.from_pretrained(args.base_model)
        tokenizer = getattr(processor, "tokenizer", processor)
        _, report, previews = build_examples(rows, make_render(processor), tokenizer, args.max_length)
        (args.output / "mask_preview.txt").write_text(previews, encoding="utf-8")
        write(args.output / "checks.json", {**receipt, **report})
        print(json.dumps(report, indent=2), "\nchecks 1-3 passed; preview in", args.output / "mask_preview.txt")
        return

    os.environ.setdefault("UNSLOTH_RETURN_LOGITS", "1")  # the cache check needs real logits
    from unsloth import FastModel  # must be imported before transformers
    import torch
    from transformers import Trainer, TrainingArguments

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not found; refusing to start a paid training run on CPU")
    model, processor = FastModel.from_pretrained(
        model_name=args.base_model, max_seq_length=args.max_length,
        load_in_4bit=True, full_finetuning=False,
    )
    tokenizer = getattr(processor, "tokenizer", processor)
    examples, report, previews = build_examples(rows, make_render(processor), tokenizer, args.max_length)
    (args.output / "mask_preview.txt").write_text(previews, encoding="utf-8")

    model = FastModel.get_peft_model(
        model,
        finetune_vision_layers=False, finetune_language_layers=True,
        finetune_attention_modules=True, finetune_mlp_modules=True,
        r=args.rank, lora_alpha=args.alpha, lora_dropout=0, bias="none",
        random_state=args.seed, use_gradient_checkpointing="unsloth",
    )
    report.update(lora_targets(model))
    report["cache_check"] = cache_check(model, examples[0])

    learning_rate = args.learning_rate or (2e-4 if args.smoke else 1e-4)
    settings = dict(
        output_dir=str(args.output), seed=args.seed, data_seed=args.seed,
        num_train_epochs=args.epochs, max_steps=20 if args.smoke else -1,
        per_device_train_batch_size=1, gradient_accumulation_steps=2 if args.smoke else 8,
        learning_rate=learning_rate, lr_scheduler_type="cosine", weight_decay=0.001,
        logging_steps=1, save_strategy="no" if args.smoke else "epoch", save_total_limit=2,
        bf16=torch.cuda.is_bf16_supported(), fp16=not torch.cuda.is_bf16_supported(),
        optim="adamw_8bit", report_to="none", remove_unused_columns=False,
    )
    warmup = "warmup_ratio" if "warmup_ratio" in inspect.signature(TrainingArguments).parameters else "warmup_steps"
    settings[warmup] = 0.05
    receipt.update({"settings": {k: v for k, v in settings.items() if k != "output_dir"},
                    "lora": {"rank": args.rank, "alpha": args.alpha, "dropout": 0}, "checks": report,
                    "packages": subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True,
                                               capture_output=True, text=True).stdout.splitlines()})
    write(args.output / "run_config.json", receipt)
    print(json.dumps(report, indent=2), flush=True)

    model.train()
    trainer = Trainer(model=model, args=TrainingArguments(**settings), train_dataset=examples,
                      data_collator=collate(tokenizer.pad_token_id or 0))
    result = trainer.train()
    model.save_pretrained(str(args.output))
    processor.save_pretrained(str(args.output))
    write(args.output / "train_metrics.json", {"metrics": result.metrics, "log": trainer.state.log_history})
    losses = [entry["loss"] for entry in trainer.state.log_history if "loss" in entry]
    print(f"done: {len(losses)} logged steps, loss {losses[0]:.3f} -> {losses[-1]:.3f}; adapter in {args.output}")


if __name__ == "__main__":
    main()
