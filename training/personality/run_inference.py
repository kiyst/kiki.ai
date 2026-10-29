"""Generate reproducible base or adapter responses for the blind personality eval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("pilot_eval.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--system-prompt", type=Path)
    parser.add_argument("--seed", type=int, default=20261029)
    parser.add_argument("--max-new-tokens", type=int, default=220)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU not found")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=dtype,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=quantization,
        device_map={"": 0},
        dtype=dtype,
    )
    if args.adapter:
        model = PeftModel.from_pretrained(model, str(args.adapter))
    model.eval()

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for case in cases:
            messages = list(case["messages"])
            if args.system_prompt:
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": args.system_prompt.read_text(encoding="utf-8").strip(),
                    },
                )
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
            encoded = tokenizer(prompt, return_tensors="pt").to(model.device)
            torch.manual_seed(args.seed)
            with torch.inference_mode():
                generated = model.generate(
                    **encoded,
                    max_new_tokens=args.max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
            answer = tokenizer.decode(
                generated[0, encoded["input_ids"].shape[1] :],
                skip_special_tokens=True,
            ).strip()
            handle.write(
                json.dumps(
                    {"id": case["id"], "label": args.label, "response": answer},
                    ensure_ascii=False,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
