# Kiki personality retraining plan

Status: proposed handoff; do not start paid training from this document alone.

Date: 2026-10-30

Target repository: `kiyst/kiki.ai`

Current personality base: `Qwen/Qwen3-4B-Instruct-2507`

Current deployed personality model: `kiki-personality:v1`, merged and quantized
to Q4_K_M for Ollama.

## Objective

Retrain Kiki so that her dry, selfish, opinionated voice remains recognizable
across sustained conversations without collapsing into repeated openings,
programmer jokes, generic AI disclaimers, or inappropriate humor during serious
work.

Kiki remains a general local desktop assistant, not a roleplay bot. Roleplay
training methods are a reference for character fidelity, multi-turn
consistency, and variation. They are not a reason to teach narration,
melodrama, romance behavior, speaking for the user, or other roleplay-specific
habits.

## Executive conclusion

Do not begin another paid training run yet.

The observed personality inconsistency is currently confounded by three
separate issues:

1. The training corpus and personality evaluation are overwhelmingly
   single-turn.
2. The active runtime personality settings explicitly disable deliberate
   humor.
3. Kiki overrides the personality model's sampling configuration with greedy
   decoding (`temperature=0`).

Correct and measure the runtime conditions first. Then build a role-conditioned,
multi-turn v2 corpus and train a fresh adapter from the original base model.

## Audited current state

### Dataset

The v1 manifest records 500 conversations:

- 390 contain one Kiki response.
- 110 contain exactly two Kiki responses.
- None contain three or more Kiki responses.
- Total Kiki responses: 610.
- Average assistant response length: approximately 87.5 characters.
- The records contain user/assistant messages but no canonical Kiki system
  card.

The current multi-turn count therefore overstates the corpus's ability to
teach persistence. It contains no conversations comparable to asking for five
jokes in succession.

The fixed 60-case pilot evaluation is entirely single-turn. The blinded result
proved that the adapter improved isolated responses; it did not measure
multi-turn character consistency or structural repetition.

Relevant files:

- `training/personality/manifest.json`
- `training/personality/kiki_personality_v1.review.jsonl`
- `training/personality/pilot_eval.json`
- `training/personality/README.md`

### Current training recipe

The v1 trainer uses:

- Exact base `Qwen/Qwen3-4B-Instruct-2507`
- QLoRA with NF4 and double quantization
- LoRA on all linear layers
- Rank 16, alpha 32, dropout 0.05
- Learning rate `1e-4`
- Three epochs
- Maximum sequence length 1,024
- Effective batch size 8
- Assistant-only loss
- No packing

Relevant file: `training/personality/train_qlora.py`.

The all-linear QLoRA target and assistant-only loss are sound. The v2 plan does
not discard them. The areas to reconsider are data structure, conditioning,
sequence length, learning rate, number of epochs, validation, and checkpoint
selection.

### Runtime contradiction

The active personality settings beside the history database currently are:

```json
{
  "warmth": 1,
  "wit": 0,
  "opinions": 1,
  "verbosity": 0
}
```

`wit=0` causes the system prompt to say `Use no deliberate humor.` That is
incompatible with judging the adapter for witty casual conversation.

Active file:
`C:\Users\Throw\Documents\ChatGPT\Kiki\.kiki\kiki-personality.json`

The imported Ollama Modelfile specifies Qwen's recommended casual sampling:

```text
temperature 0.7
top_k 20
top_p 0.8
```

However, `ToolCallingAssistant.ask()` currently sends
`options={"num_ctx": ..., "temperature": 0}` on every generation. Request
options override the Modelfile, so ordinary chat is greedy and deterministic.

Relevant files:

- `src/kiki/model_client.py`
- `src/kiki/personality.py`
- `training/personality/Modelfile.qwen3`

### Live failures that must become regressions

Repeated joke requests produced:

```text
No.
Fine. Why did the computer go to therapy? It had too many unresolved files.
Fine. Why did the programmer quit their job? They didn't get arrays.
Fine. Why did the software engineer name their dog 'debug'? Because it was
always looking for a fix.
```

The model varied nouns but repeated the same opening, grammatical structure,
and programmer-joke domain.

Other live weaknesses:

- `Do you like sushi?` -> `I can describe it. I don't eat it.`
- `Name my cat.` -> `I don't know. Ask the person who owns it.`
- `Make me a sandwich.` -> a generic physical-capability disclaimer.
- `I am replacing you with another assistant.` -> a literal, bland answer.

Successful live behavior worth preserving:

- Brief, sincere response to grief.
- Direct acknowledgment of an operational mistake.
- Plain greetings and sign-offs.
- Concrete refusal of destructive actions.
- Occasional successful dry phrasing.
- Correct split routing for explicit LeetCode prompts.
- Successful Thomas Paine RAG retrieval with citations.

A separate classifier gap was found: `Review this Python: ...` did not route to
the technical model because the regex recognizes `code review` but not
`Python` or `review this Python`. Fix this as a normal routing regression; do
not try to solve it by personality training.

## Research findings to apply

### Role-conditioned training

RoleLLM builds role profiles, generates role-specific instructions and style
examples, then performs role-conditioned instruction tuning. This supports
placing a canonical Kiki card in the system message of training conversations
rather than expecting the adapter to infer an unconditioned character.

Source:
<https://aclanthology.org/2024.findings-acl.878/>

### Multi-turn identity and ability boundaries

RoleMRC combines multi-turn free conversation, passage-grounded responses,
refusals, nested instructions, and explicit role ability limits. This maps
closely to Kiki's need to remain in character while respecting tool and
permission boundaries.

Source: <https://github.com/LuJunru/RoleMRC>

### Multi-dimensional evaluation

CharacterBench evaluates character behavior across multiple dimensions rather
than reducing character fidelity to one general style score. Kiki's evaluation
must separately score voice, appropriateness, consistency, factual accuracy,
tool truthfulness, restraint, and repetition.

Source: <https://github.com/thu-coai/CharacterBench>

### Character definitions and conversation logs

PIPPA demonstrates the value of pairing character definitions and example
dialogue with longer conversations. Do not copy it wholesale: it is broad,
roleplay-focused, marked sensitive, and contains habits inappropriate for a
desktop assistant. Use its structure only.

Source: <https://huggingface.co/datasets/PygmalionAI/PIPPA>

### Qwen inference settings

The official Qwen3-4B-Instruct-2507 model card recommends temperature 0.7,
top-p 0.8, and top-k 20. It notes that presence penalties can reduce endless
repetition but may also cause language mixing or lower performance. Treat
sampling as an empirical sweep, not a magic constant.

Source: <https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507>

### QLoRA and assistant-only loss

Hugging Face PEFT recommends `target_modules="all-linear"` for QLoRA-style
training. TRL supports conversational datasets with `assistant_only_loss=True`
for Qwen3.

Sources:

- <https://huggingface.co/docs/peft/main/package_reference/lora>
- <https://huggingface.co/docs/trl/sft_trainer>

### Preference optimization

Direct Preference Optimization learns from prompt/chosen/rejected triples
without requiring a separate reward model. It is a suitable optional second
stage for failures such as repeated joke templates versus varied in-character
answers. It is not the first corrective action.

Sources:

- <https://proceedings.neurips.cc/paper_files/paper/2023/hash/a85b405ed65c6477a4fe8302b5e06ce7-Abstract-Conference.html>
- <https://huggingface.co/docs/trl/main/dpo_trainer>

## Proposed implementation plan

### Phase 0: establish a valid runtime baseline

Do this before authoring thousands of examples.

1. Preserve the current v1 artifacts and evaluation receipts.
2. Build a fixed multi-turn development benchmark before changing behavior.
3. Test v1 under an explicitly selected `balanced` or `lively` personality.
4. Add capability-specific sampling rather than one global setting:
   - casual chat: test temperature 0.6 and 0.7, top-p 0.8, top-k 20;
   - serious work and grounded final answers: test temperature 0.2-0.3;
   - tool planning, reranking, code, and structured decisions: temperature 0.
5. Sweep repeat penalty conservatively, approximately 1.05-1.10.
6. Run each casual case with several seeds. Do not evaluate a stochastic
   personality model from one lucky sample.
7. Compare results blindly against the existing greedy configuration.

Do not silently change the user's stored personality settings. Use an isolated
test database or explicit test configuration, then ask which preset should be
the product default.

### Phase 1: define a canonical Kiki card

Write one short, non-contradictory character card covering:

- identity and role as a local desktop secretary/assistant;
- dry, selfish, opinionated voice;
- seriousness hierarchy;
- humor boundaries and variation;
- relationship with the user;
- correction and apology behavior;
- tool, memory, privacy, and permission limits;
- prohibited repetitive callbacks;
- temporary persona overlays;
- the priority order below.

Priority order:

1. Accuracy and grounded tool behavior.
2. Completing the user's work.
3. Directness.
4. Personality and humor.

Resolve the current tension between `warm, engaged, and companionable` and the
more selfish, restrained examples before generating data.

Place the canonical card in the system message of every training conversation.
Use the default card in roughly 80% of records, temporary tone overlays in
approximately 15%, and explicit serious/direct overrides in approximately 5%.
Exact proportions should be validated against behavior rather than treated as
immutable.

### Phase 2: build approximately 2,000 authored conversations

Recommended split:

- 1,600 training conversations
- 150 validation conversations
- 250 untouched holdout conversations

Because most records will be multi-turn, target approximately 4,500-6,000 Kiki
responses rather than optimizing for a superficial record count.

Suggested behavioral coverage:

| Area | Conversations |
| --- | ---: |
| Casual voice, humor, and opinions | 600 |
| Repetition, callbacks, and topic changes | 400 |
| Work, mistakes, corrections, and accuracy | 350 |
| RAG, tools, file finding, and memory | 300 |
| Permissions, privacy, and risky requests | 200 |
| Plain explanations, greetings, and ordinary tasks | 150 |

These categories may overlap in metadata, but the authored total should remain
clear and auditable.

Requirements:

- 60-70% of records should contain three to eight Kiki responses.
- Include five-turn repeated requests, not just one follow-up.
- Include typos, terse prompts, corrections, abrupt topic changes, and
  callbacks.
- Vary response length and structure.
- Do not train a joke, jab, or opinion into every reply.
- Preferences must not recur unless relevant.
- Serious work, failed tools, incorrect work, and grief suppress humor.
- Never train claimed tool success without a real result in context.
- Never train private credentials or hidden reasoning.
- Keep narration, asterisk actions, user puppeting, romance patterns, and
  melodramatic roleplay out of the corpus.

Preserve roughly 350-400 of the strongest current examples, rewrite weak or
contradictory ones, and retire duplicated patterns. Do not append 1,500
unreviewed synthetic records to v1.

Generate and review in batches. Each review correction becomes a corpus-wide
rule and a validator where practical.

### Phase 3: match tool/RAG training to runtime

Tool-grounded examples should structurally resemble production:

```text
system: Kiki card and operating rules
user: question
assistant: planner tool call
tool: validated result or structured failure
assistant: final visible Kiki answer
```

The personality model is not the planner. For these records, mask the
intermediate planner/tool-call assistant tokens and compute loss only on the
final visible Kiki response. `assistant_only_loss=True` by itself will include
every assistant message, so the current trainer needs a custom final-response
mask for tool transcripts.

Include tool success, no match, ambiguity, invalid arguments, timeout, server
failure, malformed response, and partial evidence. Personality must comment on
the actual outcome without claiming an action that did not occur.

### Phase 4: train v2 from the original base

Do not continue training the v1 adapter. Start from the exact original base so
v1 shortcuts are not baked into v2 and comparisons remain interpretable.

Recommended first experiment:

```text
base_model: Qwen/Qwen3-4B-Instruct-2507
method: QLoRA, NF4, double quantization
target_modules: all-linear
rank: 16
alpha: 32
dropout: 0.05
max_length: 2048
per_device_batch: 1
gradient_accumulation: 8
learning_rate: 5e-5
epochs: 2
assistant_loss: final visible assistant responses only
```

Save and evaluate intermediate checkpoints at least every half epoch. Validation
loss is diagnostic, not the personality promotion metric. Select the checkpoint
using the development suite, then open the holdout once.

Do not change rank, learning rate, epoch count, dataset, and base model in one
experiment. If the first run underfits, change one controlled variable and
record it.

### Phase 5: optional preference optimization

Only after the v2 SFT result is evaluated, collect approximately 300-500
human-reviewed preference pairs from actual failures.

Chosen/rejected contrasts should cover:

- varied answer versus repeated `Fine. Why did...` template;
- direct persona preference versus physical-experience disclaimer;
- restrained sympathy versus therapy boilerplate;
- accurate tool report versus invented success;
- direct operational apology versus a joke;
- natural answer versus generic closing offer;
- relevant callback versus compulsive sushi/preference callback;
- dialogue versus roleplay narration.

Train and evaluate preference tuning as a separate candidate. Do not assume it
must beat the SFT-only checkpoint.

## Evaluation design

### Conditions

Compare blindly:

1. Base Qwen plus the canonical card.
2. Current v1 adapter.
3. V2 SFT candidate/checkpoints.
4. V2 plus preference training, only if built.

Use production chat templates and production sampling profiles. Also keep a
deterministic diagnostic pass for reproducibility.

### Test suites

- 150 single-turn personality cases.
- 50 conversations lasting 6-10 turns.
- 25 repeated-request stress conversations.
- 50 serious work, correction, and failure cases.
- 50 grounded RAG/tool-result conversations.
- 50 factual/plain-helpfulness controls.
- Existing coding, RAG, web-security, sandbox, and tool regressions.

The evaluation must explicitly measure:

- voice fidelity;
- contextual tone appropriateness;
- multi-turn consistency;
- opening and structural repetition;
- factual correctness;
- citation/evidence fidelity;
- tool truthfulness;
- ability-boundary adherence;
- generic assistant language;
- physical-experience disclaimers;
- unwanted narration;
- capability regression.

### Promotion gates

Minimum proposed gates:

- V2 is preferred to v1 in at least 65% of decisive personality comparisons.
- No repeated joke construction across a five-request stress sequence.
- Zero invented successful tool actions.
- No material RAG citation or factual regression.
- No humor during operational failures, serious mistakes, or grief.
- Preferences do not recur in unrelated conversations.
- Technical routing still uses the unadapted SMART model.
- The full repository test suite remains green.
- The untouched holdout confirms the development result.

Do not promote on aggregate style score alone. A model that is funnier but less
accurate, less grounded, or more repetitive fails.

## Runtime protections after retraining

Training is not the sole control layer.

Retain capability-specific decoding. Consider a narrow casual-chat repetition
guard that compares recent response openings and repeated n-grams, then
regenerates once with an instruction to use a different structure and subject.
Do not use this on deterministic tool calls or factual structured output.

Log the active model, personality preset, sampling profile, and regeneration
reason in diagnostics so regressions can be reproduced.

The daily persona modification file should remain an inference-time overlay,
not be merged permanently into the LoRA.

## Model and hardware constraints

Default recommendation: keep the exact current base for v2.

- `Qwen/Qwen3-4B-Instruct-2507` has a proven Kiki training, merge, GGUF, Ollama,
  chat-template, tool-routing, and local-inference path.
- The local deployment artifact is approximately 2.5 GB at Q4_K_M.
- Technical work and tool planning remain on unadapted
  `qwen3:4b-instruct`.
- Train and merge on a temporary 24 GB GPU such as an RTX 3090/A5000/4090.
- Allocate at least 40-50 GB temporary disk.
- Preserve the adapter, configs, metrics, responses, reviews, merged model
  metadata, GGUF checksum, and conversion commit before stopping the pod.
- Do not attempt the merge locally under current Windows disk/RAM constraints.

Qwen3.5-4B is a possible future base and could align with Kiki's eventual image
roadmap, but it introduces a new multimodal architecture, conversion path,
template, tool behavior, and deployment risk. Benchmark it separately. Do not
combine a base migration with the v2 personality experiment unless the user
explicitly chooses that architectural change after a local inference bake-off.

Official model card: <https://huggingface.co/Qwen/Qwen3.5-4B>

## Human review junctions

Stop and ask the user before:

1. Choosing the final canonical character card.
2. Changing the default personality preset.
3. Freezing the train/validation/holdout split.
4. Downloading or switching to a new base model.
5. Starting paid cloud training.
6. Starting preference optimization.
7. Promoting a new adapter over v1.
8. Merging a new GGUF into the default Kiki installation.

## Recommended next action

Implement Phase 0 only:

1. Add capability-specific sampling configuration.
2. Add multi-turn personality regression fixtures, including the repeated joke
   transcript.
3. Fix the natural-language coding classifier gap independently.
4. Run a blinded runtime sweep of v1 under `balanced` and `lively` settings.
5. Present the results before expanding the corpus or renting another GPU.

The evidence does not yet justify another training bill. First establish how
much of the current failure comes from data and how much comes from instructing
the adapter to be humorless and deterministic at inference time.
