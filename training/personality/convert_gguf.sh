#!/usr/bin/env bash
set -Eeuo pipefail

# Merge an accepted Kiki PEFT adapter and produce an Ollama-ready Q4_K_M GGUF.
# Run this on Linux with at least 40 GB free. The adapter remains the source of
# truth; the GGUF is a replaceable deployment artifact.

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 ADAPTER_DIR OUTPUT_DIR [LLAMA_CPP_DIR]" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
adapter_dir="$(realpath "$1")"
output_dir="$(realpath -m "$2")"
llama_cpp_dir="${3:-$output_dir/llama.cpp}"
merged_dir="$output_dir/kiki-personality-v1-merged"
f16_gguf="$output_dir/kiki-personality-v1-f16.gguf"
q4_gguf="$output_dir/kiki-personality-v1-q4_k_m.gguf"
converter_venv="$output_dir/.venv-llama-convert"

mkdir -p "$output_dir"
python "$repo_root/training/personality/merge_adapter.py" \
  --adapter "$adapter_dir" \
  --output "$merged_dir" \
  --dtype bfloat16

if [[ ! -d "$llama_cpp_dir/.git" ]]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$llama_cpp_dir"
fi

# Keep llama.cpp's converter requirements away from the merge environment.
# Its requirements may select a CPU-only torch build, which is harmless for
# conversion but should not replace the CUDA torch used for PEFT merging.
python -m venv "$converter_venv"
"$converter_venv/bin/python" -m pip install --upgrade pip
"$converter_venv/bin/python" -m pip install \
  -r "$llama_cpp_dir/requirements/requirements-convert_hf_to_gguf.txt"
"$converter_venv/bin/python" "$llama_cpp_dir/convert_hf_to_gguf.py" \
  "$merged_dir" --outfile "$f16_gguf" --outtype f16

cuda_flag="${KIKI_BUILD_CUDA:-OFF}"
cuda_arch_args=()
if [[ "$cuda_flag" == "ON" ]]; then
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "KIKI_BUILD_CUDA=ON but nvidia-smi is unavailable" >&2
    exit 2
  fi
  # Building every CUDA architecture wastes paid cloud time. Compile for the
  # attached GPU unless the caller explicitly supplies another architecture.
  cuda_arch="${KIKI_CUDA_ARCH:-}"
  if [[ -z "$cuda_arch" ]]; then
    cuda_arch="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n 1 | tr -d '.' || true)"
  fi
  if [[ -n "$cuda_arch" ]]; then
    cuda_arch_args+=("-DCMAKE_CUDA_ARCHITECTURES=$cuda_arch")
  fi
fi
cmake -S "$llama_cpp_dir" -B "$llama_cpp_dir/build" \
  -DGGML_CUDA="$cuda_flag" -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release \
  "${cuda_arch_args[@]}"
cmake --build "$llama_cpp_dir/build" --config Release -j "${KIKI_BUILD_JOBS:-8}"
"$llama_cpp_dir/build/bin/llama-quantize" "$f16_gguf" "$q4_gguf" Q4_K_M
sha256sum "$q4_gguf" | tee "$q4_gguf.sha256"
git -C "$llama_cpp_dir" rev-parse HEAD > "$output_dir/llama-cpp-commit.txt"
"$llama_cpp_dir/build/bin/llama-cli" \
  -m "$q4_gguf" -ngl 0 -p "Morning." -n 32 --temp 0.7 --top-p 0.9 \
  > "$output_dir/kiki-gguf-smoke-test.txt" 2>&1
ls -lh "$f16_gguf" "$q4_gguf"
