"""Train Kiki's QLoRA personality adapter on the frozen 500-example corpus."""

from __future__ import annotations

import argparse
import json
import platform
import random
import subprocess
from pathlib import Path

BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE / "kiki_personality_v1.review.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=HERE / "artifacts" / "adapter")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--alpha", type=int, default=32)
    parser.add_argument("--smoke", action="store_true", help="Run five optimizer steps.")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        messages = row.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"line {line_number}: missing messages")
        rows.append({"messages": messages})
    if not rows:
        raise ValueError("dataset is empty")
    return rows


def receipt(args: argparse.Namespace, rows: int, packages: str) -> dict[str, object]:
    return {
        "base_model": args.base_model,
        "dataset": str(args.dataset.resolve()),
        "records": rows,
        "seed": args.seed,
        "max_length": args.max_length,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "lora_rank": args.rank,
        "lora_alpha": args.alpha,
        "smoke": args.smoke,
        "python": platform.python_version(),
        "packages": packages.splitlines(),
    }


def main() -> None:
    args = parse_args()
    rows = load_rows(args.dataset)
    args.output.mkdir(parents=True, exist_ok=True)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not found; refusing to start a paid training run on CPU")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=quantization,
        device_map={"": 0},
        dtype=compute_dtype,
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable()

    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.rank,
        lora_alpha=args.alpha,
        lora_dropout=0.05,
        bias="none",
        target_modules="all-linear",
    )
    config = SFTConfig(
        output_dir=str(args.output),
        seed=args.seed,
        data_seed=args.seed,
        max_length=args.max_length,
        num_train_epochs=args.epochs,
        max_steps=5 if args.smoke else -1,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=2 if args.smoke else 8,
        gradient_checkpointing=True,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=1,
        save_strategy="no" if args.smoke else "epoch",
        save_total_limit=2,
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        optim="paged_adamw_8bit",
        assistant_only_loss=True,
        packing=False,
        report_to="none",
    )
    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=Dataset.from_list(rows),
        processing_class=tokenizer,
        peft_config=lora,
    )

    packages = subprocess.run(
        ["python", "-m", "pip", "freeze"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (args.output / "run_config.json").write_text(
        json.dumps(receipt(args, len(rows), packages), indent=2) + "\n",
        encoding="utf-8",
    )
    result = trainer.train()
    trainer.save_model(str(args.output))
    tokenizer.save_pretrained(str(args.output))
    (args.output / "train_metrics.json").write_text(
        json.dumps(result.metrics, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
