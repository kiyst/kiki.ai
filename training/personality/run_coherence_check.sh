#!/bin/bash
# Coherence check for the v2 pilot: final vs epoch-1 adapter, temperature 1.0 vs 0.7.
# Adapter only, on a probe subset and the first 12 development conversations.
# Never uses the sealed holdout (tuning decision).
set -euo pipefail
export HF_HOME=/workspace/hf PYTHONUNBUFFERED=1
. /workspace/venv/bin/activate
cd /workspace/kiki.ai
A=/workspace/artifacts
T=training/personality
DEV=$T/recovery/2026-11-01/prepared/development.jsonl
IDS="s01 s04 s07 s10 s14 s17 n02 n07 m01 m03 m06 k01 k06 k07"
for ckpt in final:$A/v2-pilot epoch1:$A/v2-pilot/checkpoint-43; do
  name=${ckpt%%:*}; path=${ckpt#*:}
  for temp in 1.0 0.7; do
    out=$A/coherence/$name-t$temp
    [ -f "$out/done" ] && continue
    mkdir -p "$out"
    echo "== $(date -u +%FT%TZ) $name t=$temp" | tee -a $A/commands.log
    python $T/eval_v2_scripts.py --adapter "$path" --output "$out/probes" --only $IDS --seeds 1 \
      --skip-base --skip-holdout --skip-no-note --temperature $temp > "$out/probes.log" 2>&1
    python $T/eval_v2_pilot.py --adapter "$path" --dataset $DEV --output "$out/dev" --limit 12 \
      --skip-base --temperature $temp > "$out/dev.log" 2>&1
    touch "$out/done"
  done
done
echo "COHERENCE-DONE $(date -u +%FT%TZ)" | tee -a $A/commands.log
