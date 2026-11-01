#!/usr/bin/env bash
set -Eeuo pipefail

# Build llama.cpp, convert the QAT base to Q4_0 GGUF and the adapter to a GGUF
# LoRA, then run adapter_check.py. Run on the pod after a --smoke training run.
# Needs HF_TOKEN in the environment (read-only) and about 40 GB free.

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 ADAPTER_DIR WORK_DIR [LLAMA_CPP_DIR]" >&2
  exit 2
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
adapter_dir="$(realpath "$1")"
work="$(realpath -m "$2")"
llama="${3:-$work/llama.cpp}"
base="$work/gemma-4-e4b-it-qat-unquantized"
mkdir -p "$work"

if [[ ! -f "$base/config.json" ]]; then
  hf download google/gemma-4-E4B-it-qat-q4_0-unquantized --local-dir "$base"
fi
if [[ ! -d "$llama/.git" ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$llama"
fi
git -C "$llama" rev-parse HEAD > "$work/llama-cpp-commit.txt"

# Converter requirements in their own environment, away from the training torch.
if [[ ! -x "$work/.venv-convert/bin/python" ]]; then
  python -m venv "$work/.venv-convert"
  "$work/.venv-convert/bin/python" -m pip install -q --upgrade pip
  "$work/.venv-convert/bin/python" -m pip install -q -r "$llama/requirements/requirements-convert_hf_to_gguf.txt"
fi
convert="$work/.venv-convert/bin/python"

cuda="${KIKI_BUILD_CUDA:-OFF}"
cmake -S "$llama" -B "$llama/build" -DGGML_CUDA="$cuda" -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build "$llama/build" --config Release -j "${KIKI_BUILD_JOBS:-8}" --target llama-server llama-quantize

if [[ ! -f "$work/base-q4_0.gguf" ]]; then
  "$convert" "$llama/convert_hf_to_gguf.py" "$base" --outfile "$work/base-f16.gguf" --outtype f16
  "$llama/build/bin/llama-quantize" "$work/base-f16.gguf" "$work/base-q4_0.gguf" Q4_0
  rm -f "$work/base-f16.gguf"
fi
"$convert" "$llama/convert_lora_to_gguf.py" --base "$base" --outtype f16 \
  --outfile "$work/adapter.gguf" "$adapter_dir"
sha256sum "$work/base-q4_0.gguf" "$work/adapter.gguf" | tee "$work/gguf.sha256"

layers=0
if [[ "$cuda" == "ON" ]]; then layers=99; fi
python "$here/adapter_check.py" --server "$llama/build/bin/llama-server" \
  --model "$work/base-q4_0.gguf" --lora "$work/adapter.gguf" --base-dir "$base" \
  --gpu-layers "$layers" --output "$adapter_dir/adapter_check.json"
