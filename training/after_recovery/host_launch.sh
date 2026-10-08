#!/usr/bin/env bash
# Recover the original before arm and start one fresh matched after attempt.
# Numerical binaries and packed inputs come from the authenticated original intents.
set -euo pipefail
umask 077
fail() { printf 'jovovich after launch: %s\n' "$*" >&2; exit 1; }
if (( $# != 3 )); then
  printf 'usage: bash training/after_recovery/host_launch.sh TOKEN_FILE FRESH_RUN_PREFIX EXPECTED_SOURCE_SHA\n' >&2
  exit 2
fi
# The watchdog supplies only a private token-file path. Also clear credentials
# when this launcher is called directly, before creating any archive-parent child.
while IFS= read -r JOV_ENV_NAME; do
  case "${JOV_ENV_NAME^^}" in
    GIT_*|*TOKEN*|*SECRET*|*CREDENTIAL*|*PASSWORD*|*PRIVATE_KEY*|*ACCESS_KEY*|*API_KEY*) unset "$JOV_ENV_NAME" ;;
  esac
done < <(compgen -e)
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0
jov_git() { command git -c core.fsmonitor=false "$@"; }
JOV_TOKEN_FILE=$(realpath -- "$1")
JOV_LAUNCHER_PATH=$(realpath -- "${BASH_SOURCE[0]}")
JOV_RUN_PREFIX=$2
JOV_SOURCE_COMMIT=$3
[[ "$JOV_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail 'expected source SHA must be a full lowercase Git commit'
[[ -f "$JOV_TOKEN_FILE" && -r "$JOV_TOKEN_FILE" ]] || fail 'token file must be readable'
[[ "$JOV_RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$ ]] || fail 'invalid fresh run prefix (1..40 safe characters)'
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || fail 'the archived native binaries require Linux x86_64'
for JOV_TOOL in git python3 node flock; do
  command -v "$JOV_TOOL" >/dev/null || fail "missing dependency: $JOV_TOOL"
done
JOV_REPO=$(jov_git rev-parse --show-toplevel)
cd "$JOV_REPO"
[[ "$JOV_LAUNCHER_PATH" == "$JOV_REPO/training/after_recovery/host_launch.sh" ]] || fail 'use the launcher from the pinned checkout'
assert_source() {
  [[ $(jov_git rev-parse HEAD) == "$JOV_SOURCE_COMMIT" ]] || fail "checkout must be pinned to $JOV_SOURCE_COMMIT"
  jov_git diff --quiet HEAD -- || fail 'tracked checkout files have local changes'
  [[ -z $(jov_git ls-files --others --exclude-standard -- training test bin prompts deps) ]] || fail 'untracked source files are outside the reviewed commit'
}
assert_source
JOV_NOTORCH_COMMIT=$(jov_git rev-parse "$JOV_SOURCE_COMMIT:deps/notorch")
[[ "$JOV_NOTORCH_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail 'missing pinned notorch gitlink'
python3 -c 'import os, sys; sys.exit(0 if sys.version_info >= (3, 11) and not sys.flags.optimize and not os.environ.get("PYTHONOPTIMIZE") else 1)' || fail 'unoptimized Python 3.11 or newer is required'
node -e 'if (+process.versions.node.split(".")[0] < 22) process.exit(1)' || fail 'Node 22 or newer is required'
export PYTHONDONTWRITEBYTECODE=1

JOV_INPUTS=training/after_recovery/inputs.json
JOV_INFRASTRUCTURE_RECORD=training/results/2026-10-08-archive-rehearsal/launch-bindings.json
# Read the exact committed inputs and approved infrastructure pairs before any
# installation, model download, or archive recovery.
JOV_FIELDS=$(python3 - "$JOV_INPUTS" "$JOV_INFRASTRUCTURE_RECORD" "$JOV_SOURCE_COMMIT" "$JOV_RUN_PREFIX" <<'PY'
import hashlib, json, os, re, subprocess, sys
from pathlib import Path
inputs_name, record_name, source, prefix = sys.argv[1:]
root = Path.cwd().resolve()
def need(value):
    if not value:
        raise SystemExit('invalid committed after launch inputs or infrastructure record')
def committed(name):
    path = root
    for part in Path(name).parts:
        path /= part
        need(not path.is_symlink())
    need(path.is_file())
    raw = path.read_bytes()
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    def git(*args):
        return subprocess.run(['git', '-c', 'core.fsmonitor=false', '--literal-pathspecs', *args],
                              check=True, capture_output=True, env=env).stdout
    entries = git('ls-tree', '-z', source, '--', name).split(b'\0')
    need(len(entries) == 2 and entries[1] == b'')
    mode_type_oid, found_name = entries[0].split(b'\t', 1)
    mode, kind, oid = mode_type_oid.split(b' ')
    need(mode in (b'100644', b'100755') and kind == b'blob' and found_name.decode() == name)
    expected = git('cat-file', 'blob', oid.decode())
    need(raw == expected)
    return raw
value, record = (json.loads(committed(name)) for name in (inputs_name, record_name))
need(isinstance(value, dict) and set(value) == {'schema', 'original_source_commit', 'archive_revision', 'archive',
    'before_run_id', 'failed_after_run_id', 'before_plan_sha256', 'before_completion_sha256',
    'failed_after_plan_sha256', 'expected_initial_lora_sha256', 'new_after_run_id', 'new_evaluation_run_id'})
need(value['schema'] == 'jovovich.matched-after-inputs.v1')
for key in ('original_source_commit', 'archive_revision'):
    need(isinstance(value[key], str) and re.fullmatch(r'[0-9a-f]{40}', value[key]))
for key in ('before_plan_sha256', 'before_completion_sha256', 'failed_after_plan_sha256'):
    need(isinstance(value[key], str) and re.fullmatch(r'[0-9a-f]{64}', value[key]))
ids = [value[key] for key in ('before_run_id', 'failed_after_run_id', 'new_after_run_id', 'new_evaluation_run_id')]
need(all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,49}', v) for v in ids) and len(set(ids)) == 4)
need(value['new_after_run_id'] == prefix + '-after' and value['new_evaluation_run_id'] == prefix + '-eval')
need(value['archive'] == {'repo': 'ataeff/jovovich', 'prefix': 'experiments/explanation-order', 'private': True})
initial = value['expected_initial_lora_sha256']
need(isinstance(initial, dict) and set(initial) == {'gate', 'up', 'down'} and
     all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) for v in initial.values()))
need(isinstance(record, dict) and record.get('schema') == 'jovovich.archive-retry-preflight-result.v1' and
     record.get('new_after_run_id') == value['new_after_run_id'] and
     record.get('original_archive_revision') == value['archive_revision'])
changes = record.get('infrastructure_changes')
need(isinstance(changes, list) and len(changes) == 2 and
     {item.get('path') for item in changes if isinstance(item, dict)} ==
     {'training/durable_archive.py', 'training/explanations/run_training.py'})
for item in changes:
    need(set(item) == {'path', 'original', 'candidate'})
    for kind in ('original', 'candidate'):
        spec = item[kind]
        need(isinstance(spec, dict) and set(spec) == {'path', 'bytes', 'sha256'} and
             spec['path'] == item['path'] and type(spec['bytes']) is int and spec['bytes'] > 0 and
             isinstance(spec['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', spec['sha256']))
    raw = committed(item['path'])
    need(item['candidate'] == {'path': item['path'], 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
print(value['new_after_run_id'], value['new_evaluation_run_id'])
PY
) || fail 'committed continuation inputs do not match this launch'
read -r JOV_AFTER_RUN_ID JOV_EVALUATION_RUN_ID <<<"$JOV_FIELDS"

JOV_JOB="models/$JOV_RUN_PREFIX-job"
JOV_RECOVERED="models/$JOV_RUN_PREFIX-recovered"
JOV_LAUNCH="models/$JOV_RUN_PREFIX-launch"
JOV_AFTER="models/$JOV_RUN_PREFIX-after"
JOV_EVALUATION="models/$JOV_RUN_PREFIX-eval"
for JOV_PATH in "$JOV_JOB" "$JOV_RECOVERED" "$JOV_LAUNCH" "$JOV_AFTER" "$JOV_EVALUATION"; do
  [[ ! -e "$JOV_PATH" && ! -L "$JOV_PATH" ]] || fail "fresh output already exists: $JOV_PATH"
done
mkdir -p models
exec 9>models/persistent-host-launch.lock
flock -n 9 || fail 'another persistent-host launcher holds this checkout'
mkdir "$JOV_JOB"
cp -- "$JOV_LAUNCHER_PATH" "$JOV_JOB/launcher.sh"
trap 'JOV_CODE=$?; printf "launcher_exit_code=%s\n" "$JOV_CODE" >"$JOV_JOB/exit-status.txt"' EXIT

jov_git submodule update --init --recursive
assert_source
[[ $(jov_git -C deps/notorch rev-parse HEAD) == "$JOV_NOTORCH_COMMIT" ]] || fail 'notorch pin mismatch'
jov_git -C deps/notorch diff --quiet HEAD -- || fail 'tracked notorch files have local changes'
JOV_VENV="$JOV_REPO/models/archive-client-0.35.3"
[[ -x "$JOV_VENV/bin/python" ]] || python3 -m venv "$JOV_VENV"
JOV_PY="$JOV_VENV/bin/python"
"$JOV_PY" -m pip install 'huggingface_hub==0.35.3'
"$JOV_PY" -c 'import huggingface_hub; assert huggingface_hub.__version__ == "0.35.3"'
"$JOV_PY" - "$JOV_JOB" "$JOV_SOURCE_COMMIT" "$JOV_NOTORCH_COMMIT" "$JOV_REPO" "$JOV_INPUTS" "$JOV_INFRASTRUCTURE_RECORD" <<'PY'
import hashlib, json, platform, subprocess, sys
from pathlib import Path
import huggingface_hub
job, source, notorch, repo, inputs, infrastructure = sys.argv[1:]
def run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
try:
    cpuinfo = Path('/proc/cpuinfo').read_text()
except OSError:
    cpuinfo = ''
def cpu_field(key):
    return next((line.split(':', 1)[1].strip() for line in cpuinfo.splitlines() if line.split(':', 1)[0].strip() == key), None)
manifest = {'schema': 'jovovich.matched-after-host.v1', 'source_commit': source, 'notorch_commit': notorch,
            'checkout': repo, 'machine': run(['uname', '-m']), 'cpu_model': cpu_field('model name'),
            'cpu_flags': cpu_field('flags'), 'python': platform.python_version(),
            'huggingface_hub': huggingface_hub.__version__,
            'numerical_binaries': 'restored from authenticated original intent; no rebuild',
            'launch_inputs': json.loads(Path(inputs).read_text()),
            'infrastructure_record': {'path': infrastructure, 'bytes': Path(infrastructure).stat().st_size,
                'sha256': hashlib.sha256(Path(infrastructure).read_bytes()).hexdigest()}}
with (Path(job) / 'host-manifest.json').open('x') as stream:
    json.dump(manifest, stream, indent=2); stream.write('\n')
PY
JOVOVICH_MODEL="$JOV_REPO/models/base-qwen.gguf" node bin/jovovich.mjs fetch-model
assert_source
"$JOV_PY" training/after_recovery/preflight.py --output "$JOV_RECOVERED" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/recover.json"
assert_source
"$JOV_PY" training/after_recovery/bind.py --recovered "$JOV_RECOVERED" --out "$JOV_LAUNCH" \
  --source-sha "$JOV_SOURCE_COMMIT" --infrastructure-record "$JOV_INFRASTRUCTURE_RECORD" \
  --host-manifest "$JOV_JOB/host-manifest.json" >"$JOV_JOB/bind.json"
# The binder has restored the original evaluation contract at its original path
# and bound the host provenance into the new intent. Check that handoff before
# either the native protocol preflight or the training command executes.
JOV_EVALUATION_PLAN=$("$JOV_PY" - "$JOV_LAUNCH/after.launch.json" "$JOV_JOB" "$JOV_INPUTS" "$JOV_AFTER_RUN_ID" <<'PY'
import hashlib, json, sys
from pathlib import Path, PurePosixPath
plan_path, job, inputs = map(Path, sys.argv[1:4])
plan = json.loads(plan_path.read_text())
def need(value):
    if not value:
        raise SystemExit('bound after plan or host provenance differs')
def binding(path):
    need(path.is_file() and not path.is_symlink())
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
need(plan['run_id'] == sys.argv[4] and plan['arm'] == 'after' and
     plan['expected_initial_lora_sha256'] == json.loads(inputs.read_text())['expected_initial_lora_sha256'])
bindings = {item['path']: item for item in plan['bindings']}
need(len(bindings) == len(plan['bindings']))
for name in (job / 'launcher.sh', job / 'host-manifest.json', inputs, Path('training/after_recovery/host_launch.sh')):
    item = binding(name)
    need(bindings.get(item['path']) == item)
name = plan['evaluation_plan']
path = PurePosixPath(name)
need(path.parts and not path.is_absolute() and str(path) == name and
     all(p not in ('.', '..') for p in path.parts))
item = binding(Path(name))
need(Path(name).resolve().is_relative_to(Path.cwd().resolve()) and bindings.get(name) == item)
print(name)
PY
)
assert_source
"$JOV_PY" training/explanations/run_training.py preflight --plan "$JOV_LAUNCH/after.launch.json"
assert_source
printf 'Starting fresh matched after: %s\n' "$JOV_AFTER"
"$JOV_PY" training/explanations/run_training.py run --plan "$JOV_LAUNCH/after.launch.json" \
  --run-dir "$JOV_AFTER" --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/after.stdout" 2>"$JOV_JOB/after.stderr"
assert_source
printf 'Starting original before / fresh after evaluation: %s\n' "$JOV_EVALUATION"
"$JOV_PY" training/after_recovery/evaluate.py run --plan "$JOV_EVALUATION_PLAN" \
  --before "$JOV_RECOVERED/before" --after "$JOV_AFTER" --continuation-record "$JOV_LAUNCH/binding.json" \
  --output "$JOV_EVALUATION" --run-id "$JOV_EVALUATION_RUN_ID" --source-sha "$JOV_SOURCE_COMMIT" \
  --token-file "$JOV_TOKEN_FILE" >"$JOV_JOB/evaluation.stdout" 2>"$JOV_JOB/evaluation.stderr"
assert_source
printf '{"status": "matched_after_evaluation_archived", "semantic_audit": "pending", "evaluation": "%s"}\n' \
  "$JOV_EVALUATION" >"$JOV_JOB/completed.json"
printf 'Matched after evaluation archived; semantic audit pending: %s\n' "$JOV_EVALUATION"
