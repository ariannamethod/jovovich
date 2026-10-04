#!/usr/bin/env bash
# Runs as the credential-free child of the pinned runpod_bootstrap.py watchdog.
# The original experiment's /workspace/jovovich checkout remains intact.
set -euo pipefail
umask 077
while IFS= read -r JOV_ENV_NAME; do
  case "${JOV_ENV_NAME^^}" in
    GIT_*|*TOKEN*|*SECRET*|*CREDENTIAL*|*PASSWORD*|*PRIVATE_KEY*|*ACCESS_KEY*|*API_KEY*) unset "$JOV_ENV_NAME" ;;
  esac
done < <(compgen -e)
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0
jov_git() { command git -c core.fsmonitor=false "$@"; }
[[ $# == 3 ]] || { echo 'usage: prepare_after_host.sh TOKEN_FILE RUN_PREFIX SOURCE_SHA' >&2; exit 2; }
JOV_TOKEN_FILE=$1
JOV_RUN_PREFIX=$2
JOV_SOURCE_SHA=$3
JOV_PREPARE_PATH=$(realpath -- "${BASH_SOURCE[0]}")
[[ "$JOV_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$JOV_RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$ ]] || exit 2
[[ $(uname -m) == x86_64 ]] || { echo 'this bootstrap pins the x86_64 Node and numerical binaries' >&2; exit 2; }
[[ -d /workspace && ! -L /workspace ]] || { echo 'mounted workspace required' >&2; exit 2; }
mountpoint -q /workspace || { echo 'workspace must be a mounted volume' >&2; exit 2; }
JOV_CHECKOUT="/workspace/jovovich-after-$JOV_RUN_PREFIX"
[[ ! -e "$JOV_CHECKOUT" && ! -L "$JOV_CHECKOUT" ]] || { echo 'fresh after checkout required' >&2; exit 2; }
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
cmp -- "$JOV_PREPARE_PATH" training/cloud/prepare_after_host.sh
cmp -- /tmp/jovovich-runpod-bootstrap.py training/cloud/runpod_bootstrap.py
exec bash training/after_recovery/host_launch.sh "$JOV_TOKEN_FILE" "$JOV_RUN_PREFIX" "$JOV_SOURCE_SHA"
