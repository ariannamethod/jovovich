"""Continue the frozen experiment after successful training completion."""
import json
from pathlib import Path
import subprocess
import time

here=Path(__file__).resolve().parent
receipt=Path('models/counterbalanced-review-resource.json')
deadline=time.monotonic()+3*60*60
print(json.dumps({'phase':'waiting_for_training_receipt'}),flush=True)
while not receipt.exists():
    if time.monotonic()>deadline:raise SystemExit('Training receipt did not arrive within three hours.')
    time.sleep(15)
# The writer creates a small exclusive JSON file; wait for its final newline if
# the polling boundary happened to land inside that write.
for _ in range(10):
    raw=receipt.read_text()
    if raw.endswith('\n'):break
    time.sleep(1)
else:raise SystemExit('Incomplete training receipt.')
result=json.loads(raw)
assert result['exit_code']==0 and result['sources_unchanged']
output=Path('models/counterbalanced-review-counterbalanced-run.stdout')
print(json.dumps({'phase':'training_completed_starting_frozen_evaluation'}),flush=True)
with output.open('x') as stream:
    evaluated=subprocess.run(['python3',str(here/'run_counterbalanced_evaluation.py'),'counterbalanced'],stdout=stream,stderr=subprocess.STDOUT)
print(json.dumps({'phase':'evaluation_completed','exit_code':evaluated.returncode}),flush=True)
raise SystemExit(evaluated.returncode)
