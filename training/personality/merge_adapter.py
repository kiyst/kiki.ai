"""Merge a trained adapter into the base model for later GGUF conversion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--dtype",
        choices=("bfloat16", "float16"),
        default="bfloat16",
        help="Merge precision. Qwen3 training used bfloat16 on the RTX 3090.",
    )
    args = parser.parse_args()

    config_path = args.adapter / "adapter_config.json"
    if not config_path.is_file():
        parser.error(f"adapter_config.json not found in {args.adapter}")
    adapter_config = json.loads(config_path.read_text(encoding="utf-8"))
    trained_base = adapter_config.get("base_model_name_or_path")
    if trained_base != args.base_model:
        parser.error(
            "adapter/base mismatch: adapter was trained against "
            f"{trained_base!r}, requested {args.base_model!r}"
        )

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dtype = getattr(torch, args.dtype)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        dtype=dtype,
        device_map={"": "cpu"},
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    merged = PeftModel.from_pretrained(model, str(args.adapter)).merge_and_unload(
        progressbar=True
    )
    args.output.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(args.output, safe_serialization=True, max_shard_size="4GB")
    AutoTokenizer.from_pretrained(
        args.base_model, trust_remote_code=True
    ).save_pretrained(args.output)
    metadata = {
        "base_model": args.base_model,
        "adapter": str(args.adapter.resolve()),
        "dtype": args.dtype,
        "torch": torch.__version__,
    }
    (args.output / "kiki_merge_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
