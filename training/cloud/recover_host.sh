#!/usr/bin/env bash
# Short diagnostic child: read the stopped run; write new evidence only in /tmp.
set -euo pipefail
umask 077
[[ $# == 4 ]] || { echo 'usage: recover_host.sh TOKEN_FILE RECOVERY_RUN_ID SOURCE_SHA SOURCE_REPO' >&2; exit 2; }
JOV_TOKEN_FILE=$1
JOV_RECOVERY_ID=$2
JOV_RECOVERY_SOURCE=$3
JOV_RECOVERY_SOURCE_REPO=$4
[[ "$JOV_RECOVERY_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$ ]] || exit 2
[[ "$JOV_RECOVERY_SOURCE" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -r "$JOV_TOKEN_FILE" && -f /tmp/jovovich-recover.py ]] || exit 2
[[ -d /workspace/jovovich && -d /workspace/order-rp-20261003-01-host ]] || exit 2
# Resolve only local objects and ignore inherited Git repository/config overrides.
jov_git() {
  env -i PATH="$PATH" LANG=C GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0 \
    GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git --no-replace-objects "$@"
}
# SOURCE_REPO is a separate, pre-staged object store; never fetch into the stopped run.
[[ -d "$JOV_RECOVERY_SOURCE_REPO" ]] || exit 2
[[ $(jov_git -C "$JOV_RECOVERY_SOURCE_REPO" rev-parse "$JOV_RECOVERY_SOURCE^{commit}") == "$JOV_RECOVERY_SOURCE" ]] || exit 2
cmp -- "${BASH_SOURCE[0]}" <(jov_git -C "$JOV_RECOVERY_SOURCE_REPO" show "$JOV_RECOVERY_SOURCE:training/cloud/recover_host.sh")
cmp -- /tmp/jovovich-recover.py <(jov_git -C "$JOV_RECOVERY_SOURCE_REPO" show "$JOV_RECOVERY_SOURCE:training/cloud/recover_run.py")
JOV_RECOVERY_PY=/workspace/jovovich/models/archive-client-0.35.3/bin/python
[[ -x "$JOV_RECOVERY_PY" ]] || exit 2
exec "$JOV_RECOVERY_PY" /tmp/jovovich-recover.py \
  --repo /workspace/jovovich \
  --state-dir /workspace/order-rp-20261003-01-host \
  --run-prefix order-rp-20261003-01 \
  --run-id "$JOV_RECOVERY_ID" \
  --output "/tmp/$JOV_RECOVERY_ID-evidence" \
  --token-file "$JOV_TOKEN_FILE" \
  --source-repo "$JOV_RECOVERY_SOURCE_REPO" \
  --source-revision "$JOV_RECOVERY_SOURCE" \
  --host-source "${BASH_SOURCE[0]}"
