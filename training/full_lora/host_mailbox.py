#!/usr/bin/env python3
"""Execute owner-published jobs from this host's private Hugging Face mailbox."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import EntryNotFoundError

ROOT = Path('/workspace/jovovich-full-lora')
REPO = 'ataeff/jovovich'
PREFIX = 'control/full-lora-' + os.environ['RUNPOD_POD_ID']
TOKEN = (ROOT / 'hf.key').read_text().strip()
api = HfApi(token=TOKEN)
if not api.repo_info(REPO).private:
    raise SystemExit('control repository must be private')

def publish(name, payload):
    data = json.dumps(payload, sort_keys=True).encode()
    return api.upload_file(repo_id=REPO, path_in_repo=PREFIX+'/'+name,
                           path_or_fileobj=data, commit_message='JOVOVICH host status')

def status(phase, **fields):
    payload = {'phase': phase, 'updated_at': time.time(), 'pod': os.environ['RUNPOD_POD_ID'], **fields}
    publish('status.json', payload)
    print(json.dumps(payload), flush=True)

status('ready', root=str(ROOT), gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'],text=True).strip())
(ROOT/'jobs').mkdir(exist_ok=True)
while not (ROOT/'STOP').exists():
    try:
        path = hf_hub_download(REPO, PREFIX+'/next.json', token=TOKEN, force_download=True)
        job = json.loads(Path(path).read_text())
        ident = job['id']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}', ident):
            raise ValueError('invalid job id')
        directory = ROOT/'jobs'/ident
        if directory.exists():
            time.sleep(10)
            continue
        bundle = Path(hf_hub_download(REPO, job['bundle'], token=TOKEN, revision=job['revision'], force_download=True))
        if hashlib.sha256(bundle.read_bytes()).hexdigest() != job['sha256']:
            raise ValueError('source bundle checksum mismatch')
        directory.mkdir()
        with tarfile.open(bundle) as tar:
            for member in tar.getmembers():
                p = Path(member.name)
                if p.is_absolute() or '..' in p.parts or not (member.isdir() or member.isfile()):
                    raise ValueError('unsafe bundle member')
            tar.extractall(directory)
        (directory/'job.json').write_text(json.dumps(job,indent=2))
        script = directory/'run.sh'
        if not script.is_file():
            raise ValueError('missing fixed job entrypoint')
        status('running', job=ident, bundle_sha256=job['sha256'])
        log = directory/'job.log'
        env={k:v for k,v in os.environ.items() if k not in ('JOV_RUNPOD_KEY','JOV_HF_TOKEN','HF_TOKEN','RUNPOD_API_KEY')}
        with log.open('wb') as output:
            process = subprocess.Popen(['bash',str(script)], cwd=directory, stdout=output, stderr=subprocess.STDOUT, env=env)
            chunk=0
            while process.poll() is None:
                time.sleep(15)
                snapshot=log.read_bytes()
                api.upload_file(repo_id=REPO,path_in_repo=f'{PREFIX}/jobs/{ident}/log-{chunk:06d}.txt',path_or_fileobj=snapshot,commit_message='JOVOVICH job log')
                chunk+=1
            result=process.wait()
        api.upload_file(repo_id=REPO,path_in_repo=f'{PREFIX}/jobs/{ident}/final.log',path_or_fileobj=log,commit_message='JOVOVICH job closed log')
        (directory/'closed.json').write_text(json.dumps({'returncode':result}))
        status('closed',job=ident,returncode=result)
        if ((result != 0 and job.get('stop_on_failure', True)) or
                (result == 0 and job.get('stop_on_success', False))):
            (ROOT/'STOP').touch()
    except EntryNotFoundError:
        time.sleep(10)
    except Exception as exc:
        print(json.dumps({'event':'mailbox_failure','exception_type':type(exc).__name__}),flush=True)
        try:status('error',exception_type=type(exc).__name__)
        except Exception:pass
        (ROOT/'STOP').touch()
        raise SystemExit(1)
