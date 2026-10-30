"""Merge a trained adapter into the base model for later GGUF conversion."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        dtype=torch.float16,
        device_map="cpu",
        low_cpu_mem_usage=True,
    )
    merged = PeftModel.from_pretrained(model, str(args.adapter)).merge_and_unload()
    args.output.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(args.output, safe_serialization=True, max_shard_size="4GB")
    AutoTokenizer.from_pretrained(args.base_model).save_pretrained(args.output)


if __name__ == "__main__":
    main()
