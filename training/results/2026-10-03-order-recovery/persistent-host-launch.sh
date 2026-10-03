#!/usr/bin/env bash
# Run inside a persistent Linux checkout, kept alive with tmux/nohup/systemd.
# This starts a fresh 100-update before/after experiment; it does not resume weights.
set -euo pipefail
umask 077
fail() { printf 'jovovich host launch: %s\n' "$*" >&2; exit 1; }
if (( $# != 2 )); then
  printf 'usage: bash persistent-host-launch.sh TOKEN_FILE FRESH_RUN_PREFIX\n' >&2
  exit 2
fi
JOV_TOKEN_FILE=$(realpath -- "$1")
JOV_LAUNCHER_PATH=$(realpath -- "${BASH_SOURCE[0]}")
JOV_RUN_PREFIX=$2
[[ -f "$JOV_TOKEN_FILE" && -r "$JOV_TOKEN_FILE" ]] || fail 'token file must be readable'
[[ "$JOV_RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$ ]] || fail 'invalid fresh run prefix (1..40 safe characters)'
[[ $(uname -s) == Linux ]] || fail 'this launcher requires Linux'
for JOV_TOOL in git make cc python3 node flock; do
  command -v "$JOV_TOOL" >/dev/null || fail "missing dependency: $JOV_TOOL"
done
JOV_REPO=$(git rev-parse --show-toplevel)
cd "$JOV_REPO"
JOV_SOURCE_COMMIT=7b03bc7216619660fc5fb3b02e89ee1513b625e2
JOV_NOTORCH_COMMIT=014403faa76b795aefe18a4781980f5b140e0ed3
[[ $(git rev-parse HEAD) == "$JOV_SOURCE_COMMIT" ]] || fail "checkout must be pinned to $JOV_SOURCE_COMMIT"
git diff --quiet HEAD -- || fail 'tracked checkout files have local changes'
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || fail 'Python 3.11 or newer is required'
node -e 'if (+process.versions.node.split(".")[0] < 22) process.exit(1)' || fail 'Node 22 or newer is required'

JOV_JOB="models/$JOV_RUN_PREFIX-job"
JOV_NATIVE="models/$JOV_RUN_PREFIX-native"
JOV_LAUNCH="models/$JOV_RUN_PREFIX-launch"
JOV_BEFORE="models/$JOV_RUN_PREFIX-before"
JOV_AFTER="models/$JOV_RUN_PREFIX-after"
JOV_EVALUATION="models/$JOV_RUN_PREFIX-eval"
for JOV_PATH in "$JOV_JOB" "$JOV_NATIVE" "$JOV_LAUNCH" "$JOV_BEFORE" "$JOV_AFTER" "$JOV_EVALUATION"; do
  [[ ! -e "$JOV_PATH" && ! -L "$JOV_PATH" ]] || fail "fresh output already exists: $JOV_PATH"
done
mkdir -p models
exec 9>models/persistent-host-launch.lock
flock -n 9 || fail 'another persistent-host launcher holds this checkout'
mkdir "$JOV_JOB"
cp -- "$JOV_LAUNCHER_PATH" "$JOV_JOB/launcher.sh"
trap 'JOV_CODE=$?; printf "launcher_exit_code=%s\n" "$JOV_CODE" >"$JOV_JOB/exit-status.txt"' EXIT

git submodule update --init --recursive
[[ $(git -C deps/notorch rev-parse HEAD) == "$JOV_NOTORCH_COMMIT" ]] || fail 'notorch pin mismatch'
git -C deps/notorch diff --quiet HEAD -- || fail 'tracked notorch files have local changes'
JOV_VENV="$JOV_REPO/models/archive-client-0.35.3"
[[ -x "$JOV_VENV/bin/python" ]] || python3 -m venv "$JOV_VENV"
JOV_PY="$JOV_VENV/bin/python"
"$JOV_PY" -m pip install 'huggingface_hub==0.35.3'
JOVOVICH_MODEL="$JOV_REPO/models/base-qwen.gguf" node bin/jovovich.mjs fetch-model
make -j2 train-mlp probe-mlp merge-mlp harness
"$JOV_PY" training/explanations/verify_native.py --base models/base-qwen.gguf --out "$JOV_NATIVE"
"$JOV_PY" training/explanations/prepare_launches.py prepare \
  --base models/base-qwen.gguf --preflight "$JOV_NATIVE" \
  --out "$JOV_LAUNCH" --run-prefix "$JOV_RUN_PREFIX"

# Freeze the agreed timeout and the exact launcher in both plans before training.
"$JOV_PY" - "$JOV_LAUNCH" "$JOV_JOB" "$JOV_SOURCE_COMMIT" "$JOV_NOTORCH_COMMIT" <<'PY'
import hashlib, json, platform, sys
from pathlib import Path
import huggingface_hub
launch, job = map(Path, sys.argv[1:3])
expected_env = {'NT_NO_I8':'1', 'NT_QMV_THREADS':'2', 'NT_ATTN_THREADS':'2', 'NT_SIMD_THREADS':'2'}
manifest = {'source_commit':sys.argv[3], 'notorch_commit':sys.argv[4],
            'python':platform.python_version(), 'machine':platform.machine(),
            'huggingface_hub':huggingface_hub.__version__, 'ack_timeout_ms':900000,
            'training_updates_per_arm':100, 'training_environment':expected_env,
            'execution':'fresh before, matched after, native evaluation; sequential archive writers'}
with (job/'host-manifest.json').open('x') as f:
    json.dump(manifest, f, indent=2); f.write('\n')
bindings = [{'path':str(p), 'bytes':p.stat().st_size,
             'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (job/'launcher.sh', job/'host-manifest.json')]
for name in ('before.launch.json', 'after.template.json'):
    path = launch/name
    plan = json.loads(path.read_text())
    if plan['environment'] != expected_env or plan['argv'][4:9] != ['100','0.0001','40','25','joint']:
        raise SystemExit('fixed training settings differ')
    if any(b['path'] in {x['path'] for x in bindings} for b in plan['bindings']):
        raise SystemExit('launcher provenance binding already present')
    plan['ack_timeout_ms'] = 900000
    plan['bindings'] += bindings
    path.write_text(json.dumps(plan, indent=2)+'\n')
PY
"$JOV_PY" training/explanations/run_training.py preflight --plan "$JOV_LAUNCH/before.launch.json"

printf 'Starting before: %s\n' "$JOV_BEFORE"
"$JOV_PY" training/explanations/run_training.py run \
  --plan "$JOV_LAUNCH/before.launch.json" --run-dir "$JOV_BEFORE" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/before.stdout" 2>"$JOV_JOB/before.stderr"
"$JOV_PY" training/explanations/prepare_launches.py bind-after \
  --template "$JOV_LAUNCH/after.template.json" --before-run "$JOV_BEFORE" \
  --output "$JOV_LAUNCH/after.launch.json"
printf 'Starting matched after: %s\n' "$JOV_AFTER"
"$JOV_PY" training/explanations/run_training.py run \
  --plan "$JOV_LAUNCH/after.launch.json" --run-dir "$JOV_AFTER" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/after.stdout" 2>"$JOV_JOB/after.stderr"
printf 'Starting native evaluation: %s\n' "$JOV_EVALUATION"
"$JOV_PY" training/explanations/execute_evaluation.py run \
  --plan "$JOV_LAUNCH/evaluation-plan.json" --before "$JOV_BEFORE" --after "$JOV_AFTER" \
  --output "$JOV_EVALUATION" --run-id "$JOV_RUN_PREFIX-eval" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/evaluation.stdout" 2>"$JOV_JOB/evaluation.stderr"
printf 'Native evaluation archived; semantic audit pending: %s\n' "$JOV_EVALUATION"
