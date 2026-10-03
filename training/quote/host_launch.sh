#!/usr/bin/env bash
# Run in a fresh checkout pinned to the quote source commit, on a host built like the one that
# trained the before arm (same image, compiler and CPU), after the before/after job has finished.
# bind compares the rebuilt binaries byte for byte with the before run; the trainer sources embed
# no paths or build times.
set -euo pipefail
umask 077
fail() { printf 'jovovich quote launch: %s\n' "$*" >&2; exit 1; }
if (( $# != 3 )); then
  printf 'usage: bash training/quote/host_launch.sh TOKEN_FILE FRESH_RUN_PREFIX EXPECTED_SOURCE_SHA\n' >&2
  exit 2
fi
JOV_TOKEN_FILE=$(realpath -- "$1")
JOV_LAUNCHER_PATH=$(realpath -- "${BASH_SOURCE[0]}")
JOV_RUN_PREFIX=$2
JOV_SOURCE_COMMIT=$3
[[ "$JOV_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail 'expected source SHA must be a full lowercase Git commit'
[[ -f "$JOV_TOKEN_FILE" && -r "$JOV_TOKEN_FILE" ]] || fail 'token file must be readable'
# The evaluation run ID <prefix>-quote-eval must stay within 50 characters.
[[ "$JOV_RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$ ]] || fail 'invalid fresh run prefix (1..39 safe characters)'
[[ $(uname -s) == Linux ]] || fail 'this launcher requires Linux'
for JOV_TOOL in git make cc python3 node flock; do
  command -v "$JOV_TOOL" >/dev/null || fail "missing dependency: $JOV_TOOL"
done
JOV_REPO=$(git rev-parse --show-toplevel)
cd "$JOV_REPO"
[[ "$JOV_LAUNCHER_PATH" == "$JOV_REPO/training/quote/host_launch.sh" ]] || fail 'use the launcher from the pinned checkout'
assert_source() {
  [[ $(git rev-parse HEAD) == "$JOV_SOURCE_COMMIT" ]] || fail "checkout must be pinned to $JOV_SOURCE_COMMIT"
  git diff --quiet HEAD -- || fail 'tracked checkout files have local changes'
  [[ -z $(git ls-files --others --exclude-standard -- training test bin prompts deps) ]] || fail 'untracked source files are outside the reviewed commit'
}
assert_source
JOV_NOTORCH_COMMIT=$(git rev-parse "$JOV_SOURCE_COMMIT:deps/notorch")
[[ "$JOV_NOTORCH_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail 'missing pinned notorch gitlink'
# Credentials are read only by archive-parent processes from the private file.
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACE_HUB_TOKEN RUNPOD_API_KEY RUNPOD_API_TOKEN
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || fail 'Python 3.11 or newer is required'
node -e 'if (+process.versions.node.split(".")[0] < 22) process.exit(1)' || fail 'Node 22 or newer is required'

JOV_INPUTS=training/quote/launch_inputs.json
[[ -f "$JOV_INPUTS" ]] || fail "missing committed $JOV_INPUTS"
JOV_FIELDS=$(python3 - "$JOV_INPUTS" <<'PY'
import json, re, sys
value = json.load(open(sys.argv[1]))
if not isinstance(value, dict):
    raise SystemExit(1)
text = lambda key, pattern: isinstance(value.get(key), str) and re.fullmatch(pattern, value[key])
initial = value.get('expected_initial_lora_sha256')
if not (set(value) == {'schema', 'archive_revision', 'before_run_id',
        'before_eval_run_id', 'expected_initial_lora_sha256'} and
        value['schema'] == 'jovovich.quote-launch-inputs.v1' and text('archive_revision', r'[0-9a-f]{40}') and
        text('before_run_id', r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}') and
        text('before_eval_run_id', r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}') and
        isinstance(initial, dict) and set(initial) == {'gate', 'up', 'down'} and
        all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in initial.values())):
    raise SystemExit(1)
print(value['archive_revision'], value['before_run_id'], value['before_eval_run_id'])
PY
) || fail "invalid $JOV_INPUTS"
read -r JOV_ARCHIVE_REVISION JOV_BEFORE_RUN_ID JOV_BEFORE_EVAL_RUN_ID <<<"$JOV_FIELDS"

JOV_JOB="models/$JOV_RUN_PREFIX-quote-job"
JOV_BEFORE="models/$JOV_RUN_PREFIX-quote-before-run"
JOV_BEFORE_TRAIN="models/$JOV_RUN_PREFIX-quote-before-train"
JOV_BEFORE_HOLDOUT="models/$JOV_RUN_PREFIX-quote-before-holdout"
JOV_NATIVE="models/$JOV_RUN_PREFIX-quote-native"
JOV_LAUNCH="models/$JOV_RUN_PREFIX-quote-launch"
JOV_QUOTE="models/$JOV_RUN_PREFIX-quote-run"
JOV_EVALUATION="models/$JOV_RUN_PREFIX-quote-eval"
for JOV_PATH in "$JOV_JOB" "$JOV_BEFORE" "$JOV_BEFORE_TRAIN" "$JOV_BEFORE_HOLDOUT" "$JOV_NATIVE" \
    "$JOV_LAUNCH" "$JOV_QUOTE" "$JOV_EVALUATION"; do
  [[ ! -e "$JOV_PATH" && ! -L "$JOV_PATH" ]] || fail "fresh output already exists: $JOV_PATH"
done
mkdir -p models
# The same lock as the before/after launcher: one archive writer per checkout.
exec 9>models/persistent-host-launch.lock
flock -n 9 || fail 'another persistent-host launcher holds this checkout'
mkdir "$JOV_JOB"
cp -- "$JOV_LAUNCHER_PATH" "$JOV_JOB/launcher.sh"
trap 'JOV_CODE=$?; printf "launcher_exit_code=%s\n" "$JOV_CODE" >"$JOV_JOB/exit-status.txt"' EXIT

git submodule update --init --recursive
assert_source
[[ $(git -C deps/notorch rev-parse HEAD) == "$JOV_NOTORCH_COMMIT" ]] || fail 'notorch pin mismatch'
git -C deps/notorch diff --quiet HEAD -- || fail 'tracked notorch files have local changes'
JOV_VENV="$JOV_REPO/models/archive-client-0.35.3"
[[ -x "$JOV_VENV/bin/python" ]] || python3 -m venv "$JOV_VENV"
JOV_PY="$JOV_VENV/bin/python"
"$JOV_PY" -m pip install 'huggingface_hub==0.35.3'
"$JOV_PY" -c 'import huggingface_hub; assert huggingface_hub.__version__ == "0.35.3"'
# bind compares rebuilt binaries byte for byte with the before run; record what built them.
"$JOV_PY" - "$JOV_JOB" "$JOV_SOURCE_COMMIT" "$JOV_NOTORCH_COMMIT" "$JOV_REPO" "$JOV_INPUTS" <<'PY'
import json, platform, subprocess, sys
from pathlib import Path
import huggingface_hub
job, source, notorch, repo, inputs = sys.argv[1:6]
def run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
def model_name(text, key):
    return next((line.split(':', 1)[1].strip() for line in (text or '').splitlines() if line.startswith(key)), None)
try:
    cpuinfo = Path('/proc/cpuinfo').read_text()
except OSError:
    cpuinfo = None
manifest = {'schema': 'jovovich.quote-host.v1', 'source_commit': source, 'notorch_commit': notorch,
            'checkout': repo, 'cc_version': run(['cc', '--version']), 'machine': run(['uname', '-m']),
            'cpu_model': model_name(run(['lscpu']), 'Model name:') or model_name(cpuinfo, 'model name'),
            'python': platform.python_version(), 'huggingface_hub': huggingface_hub.__version__,
            'launch_inputs': json.loads(Path(inputs).read_text())}
with (Path(job) / 'host-manifest.json').open('x') as stream:
    json.dump(manifest, stream, indent=2); stream.write('\n')
PY
node training/quote/build.mjs --check training/sft_review_v7_quote.jsonl
"$JOV_PY" training/quote/evaluate_quote.py derive --check
JOVOVICH_MODEL="$JOV_REPO/models/base-qwen.gguf" node bin/jovovich.mjs fetch-model
make -j2 train-mlp probe-mlp merge-mlp harness

assert_source
"$JOV_PY" training/quote/bind_quote.py recover --run-id "$JOV_BEFORE_RUN_ID" \
  --revision "$JOV_ARCHIVE_REVISION" --out "$JOV_BEFORE" --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/recover-before.json"
for JOV_SPLIT in train holdout; do
  JOV_COLLECTED="models/$JOV_RUN_PREFIX-quote-before-$JOV_SPLIT"
  "$JOV_PY" training/quote/bind_quote.py recover --run-id "$JOV_BEFORE_EVAL_RUN_ID-before_update100-$JOV_SPLIT" \
    --revision "$JOV_ARCHIVE_REVISION" --out "$JOV_COLLECTED" --token-file "$JOV_TOKEN_FILE" \
    >"$JOV_JOB/recover-before-$JOV_SPLIT.json"
done
"$JOV_PY" - "$JOV_BEFORE/completion.json" "$JOV_INPUTS" <<'PY' || fail 'recovered before initialization differs from launch inputs'
import json, sys
completion, inputs = (json.load(open(path)) for path in sys.argv[1:3])
raise SystemExit(completion.get('initial_lora_sha256') != inputs['expected_initial_lora_sha256'])
PY
assert_source
"$JOV_PY" training/quote/bind_quote.py native --base models/base-qwen.gguf --out "$JOV_NATIVE"
mkdir "$JOV_LAUNCH"
"$JOV_PY" training/quote/bind_quote.py bind --before-recovered "$JOV_BEFORE" --native "$JOV_NATIVE" \
  --run-prefix "$JOV_RUN_PREFIX" --out "$JOV_LAUNCH/quote.launch.json" \
  --evaluation-contract training/quote/evaluation_contract.json
"$JOV_PY" training/explanations/run_training.py preflight --plan "$JOV_LAUNCH/quote.launch.json"

assert_source
printf 'Starting quote: %s\n' "$JOV_QUOTE"
"$JOV_PY" training/explanations/run_training.py run \
  --plan "$JOV_LAUNCH/quote.launch.json" --run-dir "$JOV_QUOTE" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/quote.stdout" 2>"$JOV_JOB/quote.stderr"
assert_source
printf 'Starting quote evaluation: %s\n' "$JOV_EVALUATION"
"$JOV_PY" training/quote/evaluate_quote.py run --quote-run "$JOV_QUOTE" \
  --contract training/quote/evaluation_contract.json \
  --before-collectors "$JOV_BEFORE_TRAIN" "$JOV_BEFORE_HOLDOUT" \
  --output "$JOV_EVALUATION" --run-id "$JOV_RUN_PREFIX-quote-eval" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/evaluation.stdout" 2>"$JOV_JOB/evaluation.stderr"
assert_source
printf '{"status": "quote_evaluation_archived", "semantic_audit": "pending", "evaluation": "%s"}\n' \
  "$JOV_EVALUATION" >"$JOV_JOB/completed.json"
printf 'Quote evaluation archived; semantic audit pending: %s\n' "$JOV_EVALUATION"
