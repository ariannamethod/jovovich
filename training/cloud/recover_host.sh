#!/usr/bin/env bash
# Short diagnostic child: read the stopped run; write new evidence only in /tmp.
set -euo pipefail
umask 077
[[ $# == 3 ]] || { echo 'usage: recover_host.sh TOKEN_FILE RECOVERY_RUN_ID SOURCE_SHA' >&2; exit 2; }
JOV_TOKEN_FILE=$1
JOV_RECOVERY_ID=$2
JOV_RECOVERY_SOURCE=$3
[[ "$JOV_RECOVERY_ID" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$ ]] || exit 2
[[ "$JOV_RECOVERY_SOURCE" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ -r "$JOV_TOKEN_FILE" && -f /tmp/jovovich-recover.py ]] || exit 2
[[ -d /workspace/jovovich && -d /workspace/order-rp-20261003-01-host ]] || exit 2
JOV_RECOVERY_PY=/workspace/jovovich/models/archive-client-0.35.3/bin/python
[[ -x "$JOV_RECOVERY_PY" ]] || exit 2
exec "$JOV_RECOVERY_PY" /tmp/jovovich-recover.py \
  --repo /workspace/jovovich \
  --state-dir /workspace/order-rp-20261003-01-host \
  --run-prefix order-rp-20261003-01 \
  --run-id "$JOV_RECOVERY_ID" \
  --output "/tmp/$JOV_RECOVERY_ID-evidence" \
  --token-file "$JOV_TOKEN_FILE"
