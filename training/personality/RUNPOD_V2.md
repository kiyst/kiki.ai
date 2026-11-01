# Kiki v2 trainer on RunPod (Gemma 4 E4B, Unsloth)

Smoke test only, for now: it proves the trainer and the llama.cpp adapter plan
work before any real training. Nothing here starts on its own. The v1 (Qwen)
guide is `RUNPOD.md`.

## Pod

- One 24 GB NVIDIA GPU (RTX 3090, 4090, or A5000), a current PyTorch image,
  at least 60 GB of disk (base model, GGUF conversion, llama.cpp build).
- Set `HF_TOKEN` (read-only) in the pod's environment variables or secrets.
  Accept Gemma's terms on the model page first if Hugging Face asks.
- Use the pod's terminal or SSH. No GitHub write token on the pod.

```bash
git clone https://github.com/kiyst/kiki.ai.git && cd kiki.ai
python -m pip install --upgrade pip
python -m pip install -r training/personality/requirements-unsloth.txt
nvidia-smi
```

## 1. Format, token, and mask checks (about 1 minute, no training)

```bash
python training/personality/train_unsloth.py --check-only \
  --output training/personality/artifacts/checks
cat training/personality/artifacts/checks/mask_preview.txt
```

Stop if it fails. Read the preview: only Kiki's lines may sit inside `[[ ]]`.

## 2. Smoke training (20 steps, a few minutes)

```bash
python training/personality/train_unsloth.py --smoke \
  --output training/personality/artifacts/smoke-adapter
```

It also checks that LoRA covers only the language layers and that outputs with
the cache on and off agree. Stop on any failure, out-of-memory, or NaN loss.
A loss around 13-15 at the start is normal for Gemma 4's small models.

## 3. Adapter in llama.cpp (the gate for running v2 on llama.cpp)

```bash
bash training/personality/adapter_check.sh \
  training/personality/artifacts/smoke-adapter /workspace/kiki-gguf
```

This downloads the base model, builds llama.cpp (CPU by default; set
`KIKI_BUILD_CUDA=ON` to use the GPU), converts the base to Q4_0 and the adapter to
GGUF, and runs `adapter_check.py`. It passes only if llama.cpp's prompt matches
the training format, the adapter switched off matches plain Gemma, and the
adapter switched on changes the output.

## Bring back

Copy these off the pod (they hold no secrets or personal paths):
`artifacts/checks/`, `artifacts/smoke-adapter/{run_config.json,train_metrics.json,mask_preview.txt,adapter_check.json}`,
`/workspace/kiki-gguf/{llama-cpp-commit.txt,gguf.sha256}`.

If step 3 fails, the fallback is a merged model in Ollama; nothing else changes.
