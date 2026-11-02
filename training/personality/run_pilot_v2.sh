#!/bin/bash
# Kiki v2 pilot pipeline on RunPod. Stops at the first failure.
# Every command is appended to artifacts/commands.log; each step logs to artifacts/<step>.log.
set -euo pipefail
export HF_HOME=/workspace/hf
export PYTHONUNBUFFERED=1
. /workspace/venv/bin/activate
cd /workspace/kiki.ai
A=/workspace/artifacts
P=training/personality/recovery/2026-11-01/prepared
T=training/personality
mkdir -p "$A"
{ echo "== $(date -u +%FT%TZ) commit $(git rev-parse HEAD)"; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader;
  python -c "import torch,transformers,unsloth;print('torch',torch.__version__,'transformers',transformers.__version__,'unsloth',unsloth.__version__)"; } >> "$A/commands.log" 2>&1

step() {  # step NAME CMD...
  local name=$1; shift
  if [ -f "$A/$name.done" ]; then echo "skip $name (done)"; return; fi
  echo "== $(date -u +%FT%TZ) $name: $*" | tee -a "$A/commands.log"
  "$@" > "$A/$name.log" 2>&1 || { echo "FAILED: $name (see $A/$name.log)" | tee -a "$A/commands.log"; exit 1; }
  touch "$A/$name.done"
  echo "ok $name" | tee -a "$A/commands.log"
}

step 1-check-train python $T/train_unsloth.py --check-only --dataset $P/train_reviewed.jsonl --output $A/checks-train
step 2-check-dev   python $T/train_unsloth.py --check-only --dataset $P/development.jsonl --output $A/checks-dev
step 3-smoke       python $T/train_unsloth.py --smoke --dataset $P/train_reviewed.jsonl --output $A/smoke
if [ "${UNTIL:-}" = "smoke" ]; then echo "PAUSED-AFTER-SMOKE" | tee -a "$A/commands.log"; exit 0; fi
step 4-pilot      python $T/train_unsloth.py --dataset $P/train_reviewed.jsonl --output $A/v2-pilot
step 5-eval-dev    python $T/eval_v2_pilot.py --adapter $A/v2-pilot --dataset $P/development.jsonl --output $A/eval-dev
step 6-pairs       python $T/blind_pairs.py $A/eval-dev/generations.jsonl $A/pairs
step 7-eval-scripts python $T/eval_v2_scripts.py --adapter $A/v2-pilot --output $A/eval-scripts
echo "ALL-DONE $(date -u +%FT%TZ)" | tee -a "$A/commands.log"
