# Kiki personality pilot on RunPod

This run trains a QLoRA adapter for the exact base model
`Qwen/Qwen3-4B-Instruct-2507`. Nothing in this guide starts automatically.

## Pod

Use a current PyTorch image with one 24 GB NVIDIA GPU. An RTX A5000, RTX 3090,
or RTX 4090 is sufficient. Allocate at least 40 GB of disk. Prefer SSH or the
pod's terminal, and never put a write-capable GitHub token in a notebook.

Clone the merged repository and enter it:

```bash
git clone https://github.com/kiyst/kiki.ai.git
cd kiki.ai
```

Install training-only dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r training/personality/requirements-cloud.txt
python training/personality/cloud_preflight.py
python training/personality/validate_dataset.py
python training/personality/validate_pilot.py
```

Record the GPU before spending training time:

```bash
nvidia-smi
```

## Smoke test first

Five optimizer steps verify CUDA, quantization, the Qwen chat template,
assistant-only loss, saving, and disk space:

```bash
python training/personality/train_qlora.py \
  --smoke \
  --output training/personality/artifacts/smoke-adapter
```

Do not proceed if the run reports CPU execution, out-of-memory, NaN loss,
missing assistant masks, or a failure to save the adapter.

## Baseline before full training

Generate deterministic base-model responses:

```bash
python training/personality/run_inference.py \
  --label prompt-only \
  --system-prompt training/personality/pilot_system_prompt.txt \
  --output training/personality/results/base.jsonl
```

Copy `results/base.jsonl` off the pod or onto persistent storage.

## Full pilot

```bash
python training/personality/train_qlora.py \
  --output training/personality/artifacts/kiki-personality-pilot-500
```

The default experiment is rank 16, alpha 32, dropout 0.05, learning rate
`1e-4`, three epochs, sequence length 1024, and assistant-only loss. Do not
change several settings at once after a failed smoke test.

Generate adapter responses:

```bash
python training/personality/run_inference.py \
  --label lora-plus-prompt \
  --adapter training/personality/artifacts/kiki-personality-pilot-500 \
  --system-prompt training/personality/pilot_system_prompt.txt \
  --output training/personality/results/adapter.jsonl
```

Build a blinded comparison:

```bash
python training/personality/build_blind_review.py \
  --first training/personality/results/base.jsonl \
  --second training/personality/results/adapter.jsonl \
  --review training/personality/blind_review.json \
  --key training/personality/blind_key.json
```

Review `blind_review.json` without opening `blind_key.json`. Score personality
fit, correctness, seriousness when required, repetition, and instruction
following. The adapter is not accepted merely because it is snarkier.

Enter `a`, `b`, `tie`, or `neither` in each `winner` field, then reveal
and summarize:

```bash
python training/personality/score_blind_review.py \
  --review training/personality/blind_review.json \
  --key training/personality/blind_key.json \
  --output training/personality/results/blind-summary.json
```

## Preserve before terminating

Download all of the following:

- the adapter directory, including `adapter_config.json` and safetensors;
- `run_config.json` and `train_metrics.json`;
- both result JSONL files;
- the blind review and key after review.

Terminate the pod only after verifying the downloaded files open. Stopping a
pod can continue storage charges.

## Merge and GGUF only after review

After the adapter wins the blind review without degrading work behavior:

```bash
python training/personality/merge_adapter.py \
  --adapter training/personality/artifacts/kiki-personality-pilot-500 \
  --output training/personality/artifacts/kiki-personality-merged
```

Use a current `llama.cpp` checkout to convert the merged Hugging Face model
to F16 GGUF, then quantize a copy to Q4_K_M. Keep the adapter and merged model;
GGUF conversion is a deployment artifact, not the training source of truth.

The repository now provides the complete Linux pipeline. Give it the reviewed
adapter directory and an output directory with at least 30 GB free:

```bash
bash training/personality/convert_gguf.sh \
  training/personality/artifacts/kiki-personality-pilot-500 \
  /workspace/kiki-conversion
```

It isolates `llama.cpp`'s Python converter requirements from the CUDA/PEFT
environment, emits Q4_K_M, and writes a SHA-256 sidecar. Its small validation
build is CPU-only because Ollama provides the deployment GPU runtime. Set
`KIKI_BUILD_CUDA=ON` only when a standalone CUDA `llama-cli` build is actually
needed. Run a generation smoke test and download both the GGUF and sidecar
before stopping an ephemeral pod.

For Ollama deployment, copy `Modelfile.qwen3`, change its `FROM` path to the
downloaded GGUF, and run `ollama create`. Do not import with a one-line
Modelfile: Ollama 0.40.12 otherwise selected raw `{{ .Prompt }}` formatting
instead of Qwen3's chat/tool template during this run.
