"""Fail fast before downloading the model or starting paid GPU work."""

from __future__ import annotations

import json
import platform


def main() -> None:
    import accelerate
    import bitsandbytes
    import datasets
    import peft
    import torch
    import transformers
    import trl

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable; do not start training")
    device = torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(device)
    gib = properties.total_memory / 1024**3
    report = {
        "python": platform.python_version(),
        "gpu": properties.name,
        "vram_gib": round(gib, 2),
        "cuda": torch.version.cuda,
        "bf16": torch.cuda.is_bf16_supported(),
        "packages": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "trl": trl.__version__,
            "peft": peft.__version__,
            "datasets": datasets.__version__,
            "accelerate": accelerate.__version__,
            "bitsandbytes": bitsandbytes.__version__,
        },
    }
    print(json.dumps(report, indent=2))
    if gib < 20:
        raise SystemExit("Less than 20 GiB VRAM; use a 24 GiB pod for the default run")


if __name__ == "__main__":
    main()
