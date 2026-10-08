import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

OLD = Path('/workspace/jovovich-after-order-rp-20261008-03')
RUN = OLD / 'models/order-rp-20261008-03-after'
PROBE = Path('/workspace/storage-probe-20261008-01')
LOCAL = Path('/tmp/storage-probe-20261008-01')
ARCHIVE_SHA = '9d29059e852d8f81033df2048b234d636d89c208becb25b29a431439c822a20d'
source = OLD / 'training/durable_archive.py'
assert hashlib.sha256(source.read_bytes()).hexdigest() == ARCHIVE_SHA
sys.path.insert(0, str(OLD / 'training'))
from durable_archive import DurableArchive, HFTransport, ArchiveError, _source_stat, _digest

PROBE.mkdir(mode=0o700, exist_ok=False)
LOCAL.mkdir(mode=0o700, exist_ok=False)
token = Path(sys.argv[1]).read_text().strip()
transport = HFTransport('ataeff/jovovich', token)
archive = DurableArchive(transport, 'storage-probe-20261008-01', 'experiments/storage-probe')
sequence = 0
start = time.monotonic()
records = []
stat_names = ['device', 'inode', 'size', 'mtime_ns', 'ctime_ns']

def save_unit(label, value, extras=None):
    global sequence
    path = LOCAL / (label + '.json')
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    files = {path.name: path, **(extras or {})}
    receipt = archive.sync_unit(label, files, sequence=sequence)
    sequence += 1
    print(json.dumps({'probe_unit': label, 'revision': receipt['revision'],
                      'elapsed_seconds': round(time.monotonic()-start, 3)}), flush=True)

payloads = {}
extras = {'probe.py': Path(__file__)}
for suffix in ['raw.jsonl', 'metrics.jsonl', 'stderr']:
    original = RUN / '_units' / ('update-038.' + suffix)
    raw = original.read_bytes()
    copy = LOCAL / ('original-update-038.' + suffix)
    copy.write_bytes(raw)
    extras[copy.name] = copy
    payloads[suffix] = raw
mount_lines = [line for line in Path('/proc/mounts').read_text().splitlines()
               if len(line.split()) > 2 and line.split()[1] == '/workspace']
mounts = [{'mountpoint': line.split()[1], 'filesystem': line.split()[2],
           'options': line.split()[3]} for line in mount_lines]
save_unit('intent', {'schema':'jovovich.source-stat-probe.v1',
    'started_utc': datetime.now(timezone.utc).isoformat(),
    'original_run':'order-rp-20261008-03-after', 'source_sha256':ARCHIVE_SHA,
    'mounts':mounts, 'model_calls':0,
    'files':{key:{'size':len(value),'sha256':hashlib.sha256(value).hexdigest()}
             for key,value in payloads.items()}}, extras)

tracked = []
for body, directory in [('network',PROBE), ('local',LOCAL)]:
    for index in range(32):
        for suffix, raw in payloads.items():
            name = 'unit-%03d.%s' % (index,suffix)
            path = directory/name
            with path.open('xb') as f:
                f.write(raw); f.flush(); os.fsync(f.fileno())
            initial = _source_stat(path)
            digest = _digest(path)
            tracked.append((body,name,path,initial,digest))

sample_start = time.monotonic()
all_changes = []
for sample, target in enumerate([0,1,2,5,10,20,30,45,60,90,120]):
    delay = target - (time.monotonic()-sample_start)
    if delay > 0:
        time.sleep(delay)
    batch = []
    for body,name,path,initial,digest in tracked:
        before = _source_stat(path)
        observed = _digest(path)
        after = _source_stat(path)
        changed = [key for key,a,b in zip(stat_names,initial,before) if a != b]
        row = {'sample':sample,'body':body,'name':name,'initial_stat':list(initial),
               'before_stat':list(before),'after_stat':list(after),
               'changed_fields':changed,'expected':digest,'observed':observed,
               'content_equal':observed == digest}
        batch.append(row)
        if changed or before != after or observed != digest:
            all_changes.append(row)
    records.extend(batch)
    print(json.dumps({'sample':sample,'files':len(batch),
                      'changes':sum(bool(r['changed_fields']) or not r['content_equal'] for r in batch)}),flush=True)
    if sample in (0,5,8,10):
        save_unit('sample-%02d'%sample, {'records':records})
        records=[]

save_unit('completed', {'status':'completed','model_calls':0,
    'files_per_body':96,'samples':11,'observations':2112,
    'changes':all_changes,'finished_utc':datetime.now(timezone.utc).isoformat()})
