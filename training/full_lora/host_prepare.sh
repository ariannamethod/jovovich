#!/bin/bash
set -euo pipefail
umask 077
export JOV_STARTED=${JOV_STARTED:-$(date +%s)}
export DEBIAN_FRONTEND=noninteractive
mkdir -p /workspace/jovovich-full-lora
cd /workspace/jovovich-full-lora
exec > >(tee -a setup.log) 2>&1
timeout 1200 apt-get update -qq
timeout 1200 apt-get install -y -qq python3 python3-pip python3-venv git ca-certificates curl openssh-server libopenblas-dev build-essential pkg-config
python3 /tmp/jovovich-watchdog.py &
trap 'touch /workspace/jovovich-full-lora/STOP' ERR
mkdir -p /root/.ssh /run/sshd
chmod 700 /root/.ssh
printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
ssh-keygen -A
printf '\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' >> /etc/ssh/sshd_config
/usr/sbin/sshd
printf '%s' "$JOV_HF_TOKEN" > hf.key
chmod 600 hf.key
unset JOV_RUNPOD_KEY JOV_HF_TOKEN
test -d jovovich/.git || git clone https://github.com/ariannamethod/jovovich.git jovovich
git -C jovovich checkout "$JOV_SOURCE"
test -d notorch/.git || git clone https://github.com/ariannamethod/notorch.git notorch
git -C notorch checkout "$JOV_NOTORCH"
python3 -m venv venv
venv/bin/pip -q install huggingface_hub==0.35.3
venv/bin/python - <<'PY'
from pathlib import Path
import hashlib, json, os
from huggingface_hub import hf_hub_download
root=Path('/workspace/jovovich-full-lora')
lock=json.loads((root/'jovovich/model.json').read_text())
p=Path(hf_hub_download(lock['repo'], lock['file'], revision=lock['revision'], local_dir=root/'models', token=(root/'hf.key').read_text()))
h=hashlib.sha256()
with p.open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
if p.stat().st_size != lock['bytes'] or h.hexdigest()!=lock['sha256']:
    raise SystemExit('base checksum mismatch')
if not (root/'base.gguf').exists(): (root/'base.gguf').symlink_to(p)
print(json.dumps({'base_verified':True,'sha256':h.hexdigest()}),flush=True)
PY
python3 jovovich/training/prepare.py curriculum.bin --sft jovovich/training/sft_review_v6_before.jsonl --sft-only
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
nvcc --version
touch READY
echo JOVOVICH_HOST_READY
venv/bin/python /tmp/jovovich-mailbox.py
wait
