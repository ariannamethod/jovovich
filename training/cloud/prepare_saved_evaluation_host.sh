#!/usr/bin/env bash
# Runs as the credential-free child of the pinned runpod_bootstrap.py watchdog.
# Restores authenticated saved endpoints; this script invokes no trainer.
set -euo pipefail
umask 077
while IFS= read -r JOV_ENV_NAME; do
  case "${JOV_ENV_NAME^^}" in
    GIT_*|*TOKEN*|*SECRET*|*CREDENTIAL*|*PASSWORD*|*PRIVATE_KEY*|*ACCESS_KEY*|*API_KEY*) unset "$JOV_ENV_NAME" ;;
  esac
done < <(compgen -e)
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0
jov_git() { command git -c core.fsmonitor=false "$@"; }
[[ $# == 3 ]] || { echo 'usage: prepare_saved_evaluation_host.sh TOKEN_FILE RUN_PREFIX SOURCE_SHA' >&2; exit 2; }
JOV_TOKEN_FILE=$1
JOV_RUN_PREFIX=$2
JOV_SOURCE_SHA=$3
JOV_PREPARE_PATH=$(realpath -- "${BASH_SOURCE[0]}")
[[ "$JOV_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$JOV_RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$ ]] || exit 2
[[ $(uname -m) == x86_64 ]] || { echo 'this bootstrap pins the x86_64 Node and numerical binaries' >&2; exit 2; }
[[ -d /workspace && ! -L /workspace ]] || { echo 'mounted workspace required' >&2; exit 2; }
mountpoint -q /workspace || { echo 'workspace must be a mounted volume' >&2; exit 2; }
JOV_CHECKOUT="/tmp/jovovich-eval-$JOV_RUN_PREFIX"
[[ ! -e "$JOV_CHECKOUT" && ! -L "$JOV_CHECKOUT" ]] || { echo 'fresh evaluation checkout required' >&2; exit 2; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends build-essential git ca-certificates curl xz-utils util-linux
JOV_NODE_VERSION=v22.23.3
JOV_NODE_ARCHIVE="node-$JOV_NODE_VERSION-linux-x64.tar.xz"
JOV_NODE_SHA=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de
curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
  "https://nodejs.org/dist/$JOV_NODE_VERSION/$JOV_NODE_ARCHIVE" -o "/tmp/$JOV_NODE_ARCHIVE"
printf '%s  %s\n' "$JOV_NODE_SHA" "/tmp/$JOV_NODE_ARCHIVE" | sha256sum --check --status
tar -xJf "/tmp/$JOV_NODE_ARCHIVE" -C /usr/local --strip-components=1
jov_git clone --no-checkout https://github.com/ariannamethod/jovovich.git "$JOV_CHECKOUT"
cd "$JOV_CHECKOUT"
jov_git checkout --detach "$JOV_SOURCE_SHA"
[[ $(jov_git rev-parse HEAD) == "$JOV_SOURCE_SHA" ]] || exit 2
cmp -- "$JOV_PREPARE_PATH" training/cloud/prepare_saved_evaluation_host.sh
cmp -- /tmp/jovovich-runpod-bootstrap.py training/cloud/runpod_bootstrap.py
# Evaluation runs on local disk; every closed unit still crosses the HF readback barrier.
jov_git submodule update --init --recursive
JOV_PIN=$(jov_git rev-parse "$JOV_SOURCE_SHA:deps/notorch")
[[ $(jov_git -C deps/notorch rev-parse HEAD) == "$JOV_PIN" ]] || exit 2
mkdir models
python3 -m venv models/archive-client
JOV_PY="$JOV_CHECKOUT/models/archive-client/bin/python"
"$JOV_PY" -m pip install 'huggingface_hub==0.35.3'
JOVOVICH_MODEL="$JOV_CHECKOUT/models/base-qwen.gguf" node bin/jovovich.mjs fetch-model
JOV_RECORD=training/results/2026-10-09-saved-evaluation/admission.json
"$JOV_PY" - "$JOV_TOKEN_FILE" "$JOV_RECORD" "$JOV_RUN_PREFIX" <<'PYRECOVER'
import json,sys
from pathlib import Path
sys.path.insert(0,'training')
from durable_archive import HFTransport, DurableArchive, ArchiveError
record=json.loads(Path(sys.argv[2]).read_text())
if record['evaluation_run_id'] != sys.argv[3]+'-eval':
    raise SystemExit('evaluation run prefix differs from committed admission')
try:
    transport=HFTransport('ataeff/jovovich',Path(sys.argv[1]).read_text().strip())
    destination=Path('models')/(sys.argv[3]+'-parent')
    result=DurableArchive(transport,record['parent_run_id'],'experiments/explanation-order').recover(
        destination,revision=record['parent_archive_revision'])
    print(json.dumps({'status':'parent_recovered','units':result['next_sequence'],
                      'verified_remote_bytes':result['verified_remote_bytes']}),flush=True)
except ArchiveError as error:
    print(json.dumps({'status':'parent_recovery_failed','archive_error':error.diagnostic}),flush=True)
    raise SystemExit(1) from None
PYRECOVER
jov_git diff --quiet HEAD -- || exit 2
exec "$JOV_PY" training/after_recovery/evaluate_saved.py run \
  --recovered "models/$JOV_RUN_PREFIX-parent" --record "$JOV_RECORD" \
  --output "models/$JOV_RUN_PREFIX-eval" --source-sha "$JOV_SOURCE_SHA" \
  --token-file "$JOV_TOKEN_FILE"
