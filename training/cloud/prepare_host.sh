#!/usr/bin/env bash
# Runs as the credential-free child of runpod_bootstrap.py.
set -euo pipefail
umask 077
[[ $# == 3 ]] || { echo 'usage: prepare_host.sh TOKEN_FILE RUN_PREFIX SOURCE_SHA' >&2; exit 2; }
JOV_TOKEN_FILE=$1
JOV_RUN_PREFIX=$2
JOV_SOURCE_SHA=$3
[[ "$JOV_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
[[ "$JOV_RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$ ]] || exit 2
[[ $(uname -m) == x86_64 ]] || { echo 'this bootstrap pins the x86_64 Node build' >&2; exit 2; }
[[ -d /workspace && ! -e /workspace/jovovich ]] || { echo 'fresh mounted workspace required' >&2; exit 2; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends build-essential git ca-certificates curl xz-utils util-linux
mountpoint -q /workspace || { echo 'workspace must be a mounted volume' >&2; exit 2; }
JOV_NODE_VERSION=v22.23.3
JOV_NODE_ARCHIVE="node-$JOV_NODE_VERSION-linux-x64.tar.xz"
JOV_NODE_SHA=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de
curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
  "https://nodejs.org/dist/$JOV_NODE_VERSION/$JOV_NODE_ARCHIVE" -o "/tmp/$JOV_NODE_ARCHIVE"
printf '%s  %s\n' "$JOV_NODE_SHA" "/tmp/$JOV_NODE_ARCHIVE" | sha256sum --check --status
tar -xJf "/tmp/$JOV_NODE_ARCHIVE" -C /usr/local --strip-components=1
git clone --no-checkout https://github.com/ariannamethod/jovovich.git /workspace/jovovich
cd /workspace/jovovich
git checkout --detach "$JOV_SOURCE_SHA"
[[ $(git rev-parse HEAD) == "$JOV_SOURCE_SHA" ]] || exit 2
# The executed bootstrap must be the same file in the pinned public tree.
cmp -- "${BASH_SOURCE[0]}" training/cloud/prepare_host.sh
cmp -- /tmp/jovovich-runpod-bootstrap.py training/cloud/runpod_bootstrap.py
exec bash training/explanations/persistent_host_launch.sh "$JOV_TOKEN_FILE" "$JOV_RUN_PREFIX" "$JOV_SOURCE_SHA"
