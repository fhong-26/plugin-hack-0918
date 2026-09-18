# Personalization lab

The primary measure is **preferred choices / eligible held-out choices** before
and after learning, on identical cases. The other measures are objective routing
correctness, errors, deferrals, inference time and independent task acceptance.
See [the lab report](../docs/PERSONALIZATION_LAB_REPORT.md) for measured results.

## Arms and frozen data

`datasets/preference-v1` has 360 authored synthetic scenarios: three profiles,
216 training, 72 validation and 72 test cases. Domains, scenario families and
sentence templates are separated by split. Candidate order varies. Only the
training split supplies correction examples. No final test labels appear in
model prompts or training. Expected choices are synthetic author labels, not
observations from real users.

The CPU pilot fixes seed 31, 12 randomly selected training examples per user,
rank 4, final two layers, q/v projection LoRA, one epoch, AdamW learning rate
0.0002. It is a small feasibility experiment, not a converged hyperparameter
search. Validation chooses the residual learning rate and checks activation;
final test results cannot change these choices.

* `current`: existing rule-first path plus frozen Qwen, no personal context.
* `memory`: identical frozen Qwen plus declared preferences and one relevant
  training correction. This is the control for merely supplying context.
* `residual`: the same context plus a trained small logit adjustment policy.
* `lora`: the same context plus actual trained Qwen attention adapters.
* `codex-reference`: isolated real Codex constrained choices with the same
  preferences/history. It does not execute the selected target tool.

The meaningful training effect is LoRA or residual **versus memory**, in addition
to the user-facing before/after comparison versus `current`. The CPU model is
the explicit `qwen3-0.6b-torch` alias, not the original default Qwen2.5 RLCD/MLX
backend. Their performance must not be conflated.

## Reproduce on Windows CPU

Use Python 3.12. The commands below assume the repository root and PowerShell.
Downloads and live Codex requests need network access and existing authorization.

```powershell
uv venv --python 3.12 .lab-venv
uv pip install --python .lab-venv\Scripts\python.exe torch==2.7.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .lab-venv\Scripts\python.exe transformers==4.57.6 peft==0.18.1 psutil==7.2.2 pytest==8.4.2
uv pip install --python .lab-venv\Scripts\python.exe -e plugins/rippletide -e user_tests
$env:RIPPLETIDE_DATA_DIR = "$PWD/.lab-cache/models"
.\.lab-venv\Scripts\rippletide.exe setup --model qwen3-0.6b-torch --skip-warmup
.\.lab-venv\Scripts\python.exe scripts/personalization_lab.py run --dataset experiments/datasets/preference-v1 --output .lab-runs/reproduction --data-dir .lab-cache/models --train-limit 12 --epochs 1 --rank 4 --layers 2
```

The `cpu-lab` project extra offers the pinned portable dependencies as well.
The default plugin install continues to use MLX on supported Apple Silicon.
Do not attempt the MLX runner on Windows. GPU acceleration is not required for
this small CPU experiment; memory and latency can still make it impractical
for interactive routing.

```powershell
npm.cmd ci --prefix tools/codex --ignore-scripts --no-audit --no-fund
.\.lab-venv\Scripts\python.exe scripts/personalization_lab.py codex-reference --dataset experiments/datasets/preference-v1 --output .lab-runs/codex-reference --model gpt-6-astra --effort high --train-limit 12
.\.lab-venv\Scripts\python.exe scripts/personalization_lab.py task --dataset experiments/datasets/preference-v1 --component-run .lab-runs/reproduction --data-dir .lab-cache/models --output .lab-runs/task-pilot --arm baseline --model gpt-6-astra --effort high
```

Repeat `task` with `current`, `memory`, and validated `residual`/`lora` profiles.
Use a new output directory for repeated attempts; preserve failures. Task runs
use actual fixture MCPs, the skill and routing hook from this checkout, named
specialists, disposable code copies and an independent acceptance grader.
They test development components, not marketplace installation. The CPU task
pilot explicitly uses a 120-second routing timeout; production remains two
seconds. Unavailable shell/sandbox/agent prerequisites are infrastructure
failures, not model accuracy failures. Rejected learned profiles are never
silently promoted for task execution.

The supplemental saved-rules diagnostic and shareable report export are:

```powershell
.\.lab-venv\Scripts\python.exe scripts/personalization_lab.py rules-reference --dataset experiments/datasets/preference-v1 --output .lab-runs/rules-reference
uv pip install --python .lab-venv\Scripts\python.exe matplotlib==3.10.8
$env:MPLCONFIGDIR = "$PWD/.lab-cache/matplotlib"
.\.lab-venv\Scripts\python.exe scripts/personalization_lab.py export --component-run .lab-runs/reproduction --reference-run .lab-runs/codex-reference --rules-reference .lab-runs/rules-reference --task-root .lab-runs/task-pilot --dataset experiments/datasets/preference-v1 --output docs/assets/personalization
```

Export requires the completed four-arm component run, including all LoRA
adapters. It produces JSON plus PNG/SVG figures and audits the retained Codex
reference rollouts for tool calls. The saved-rules control is unconditional,
whereas the authored user preferences are conditional on task suitability.

## Artifacts and checks

`.lab-runs` and `.lab-cache` are ignored. Runs retain identities, dataset digests,
prompts, candidate logits/probabilities, per-case results, adapter checksums,
training statistics, validation gates, and raw Codex task evidence. Temporary
Codex authentication is removed when each run finishes. Do not publish private
user corrections or raw real-project transcripts. The report's shareable JSON
contains only this synthetic experiment's aggregate evidence.

```powershell
.\.lab-venv\Scripts\python.exe -m pytest plugins/rippletide/tests user_tests/tests experiments/tests -q
```

The tiny-transformer regression checks real adapter gradients, unchanged frozen
base weights, equivalence of cached-prefix training inputs, and restoration of
base behavior after unloading adapters. MLX-specific runtime tests require an
Apple Silicon host. A real-user evaluation should add consented preference
labels, multiple training sizes/seeds, harder ambiguous scenarios, registry
changes and preference drift before drawing product conclusions.

## Supplemental AMD DirectML probe

Vega 7 was also tested in an isolated DirectML environment. These probes do not
change the main experiment, install a GPU routing backend, or measure complete
model inference. The second uses actual frozen Qwen suffix weights and one
cached training input, with a reduced output head and an arbitrary target.

```powershell
uv venv --python 3.12 .lab-dml-venv
uv pip install --python .lab-dml-venv/Scripts/python.exe torch-directml==0.2.5.dev240914 transformers==4.57.6 peft==0.18.1 numpy==1.26.4 psutil==7.2.2
.\.lab-dml-venv\Scripts\python.exe scripts/probe_directml.py --output .lab-runs/dml-compatibility.json
.\.lab-dml-venv\Scripts\python.exe scripts/probe_directml_qwen_suffix.py --artifacts .lab-cache/models/models/qwen3-0.6b-torch/artifacts.json --component-run .lab-runs/reproduction --output .lab-runs/dml-suffix-cpu.json --device cpu --steps 1
.\.lab-dml-venv\Scripts\python.exe scripts/probe_directml_qwen_suffix.py --artifacts .lab-cache/models/models/qwen3-0.6b-torch/artifacts.json --component-run .lab-runs/reproduction --output .lab-runs/dml-suffix-gpu.json --device directml --steps 2
```

DirectML's package requires PyTorch 2.4.1; do not install it over the controlled
CPU run's PyTorch 2.7.1 environment. The report records numerical comparisons,
CPU fallback warnings and the limited scope of the timing results.
