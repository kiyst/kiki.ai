#!/bin/bash
# Prompt-only test (2026-11-02): base Gemma with tuned sampling and a Capri-style voice
# section, against the adapter with the same sampling. Probe subset + 12 development
# conversations; never the sealed holdout.
set -euo pipefail
export HF_HOME=/workspace/hf PYTHONUNBUFFERED=1
. /workspace/venv/bin/activate
cd /workspace/kiki.ai
A=/workspace/artifacts
T=training/personality
OUT=$A/variants
IDS="s01 s04 s07 s10 s14 s17 n02 n07 m01 m03 m06 k01 k06 k07"
TUNED="--temperature 0.8 --min-p 0.05 --dry-multiplier 0.8"
VOICE="--voice-section $T/eval/voice_in_practice.txt"
python - <<'PY'
import sys, torch; sys.path.insert(0, "training/personality")
import eval_variants as v
d = v.dry_processor(0.8, breakers=set())
s = d(torch.tensor([[1, 2, 3, 4, 9, 1, 2, 3]]), torch.zeros(1, 10))
assert abs(s[0, 4].item() + 1.4) < 1e-6 and s[0, 9].item() == 0, s
print("dry self-test ok")
PY
run() { local name=$1; shift; [ -f "$OUT/$name/config.json" ] && return
  echo "== $(date -u +%FT%TZ) variant $name" | tee -a $A/commands.log
  python $T/eval_variants.py --name $name --output $OUT --only $IDS --limit 12 "$@" > "$OUT-$name.log" 2>&1; }
mkdir -p $OUT
run b-default
run b-tuned $TUNED
run b-voice $TUNED $VOICE
run b-voice-trims $TUNED $VOICE --trims
run a-tuned $TUNED --adapter $A/v2-pilot
echo "VARIANTS-DONE $(date -u +%FT%TZ)" | tee -a $A/commands.log
