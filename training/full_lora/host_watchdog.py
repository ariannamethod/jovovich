#!/usr/bin/env python3
"""Stop this paid GPU host after a closed job, setup failure, or six hours."""
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT = Path('/workspace/jovovich-full-lora')
ROOT.mkdir(parents=True, exist_ok=True)
os.chmod(ROOT, 0o700)
key = os.environ.pop('JOV_RUNPOD_KEY')
pod = os.environ['RUNPOD_POD_ID']
previous = ROOT / 'watchdog.json'
prior = json.loads(previous.read_text()) if previous.exists() else {}
started = float(prior.get('started', os.environ['JOV_STARTED']))
deadline = started + 21600
state = ROOT / 'watchdog.json'
while time.time() < deadline and not (ROOT / 'STOP').exists():
    state.write_text(json.dumps({'pod': pod, 'started': started, 'deadline': deadline,
                                 'updated': time.time(), 'status': 'running'}))
    time.sleep(10)
reason = 'closed-job' if (ROOT / 'STOP').exists() else 'six-hour-deadline'
state.write_text(json.dumps({'pod': pod, 'started': started, 'deadline': deadline, 'reason': reason, 'status': 'stopping'}))
for attempt in range(8):
    try:
        request = urllib.request.Request('https://api.runpod.io/v2/pods/' + pod + '/action',
            data=b'{"action":"stop"}', method='POST', headers={
                'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                'User-Agent': 'jovovich-full-lora-watchdog'})
        with urllib.request.urlopen(request, timeout=15) as response:
            if 200 <= response.status < 300:
                break
    except Exception:
        time.sleep(min(2 ** attempt, 30))
else:
    state.write_text(json.dumps({'pod': pod, 'started': started, 'deadline': deadline, 'reason': reason, 'status': 'stop-api-failed'}))
    raise SystemExit(1)
