"""Guarded reproduction entry point; retain the already-frozen historical helpers."""
import os
import runpy
import sys
from pathlib import Path

if sys.flags.optimize != 0 or os.environ.get('PYTHONOPTIMIZE'):
    raise RuntimeError('Checkpoint controls require Python assertions; optimization is forbidden before any work.')
if len(sys.argv) != 2 or sys.argv[1] not in ('prepare', 'run'):
    raise SystemExit('usage: python3 replay_checkpoint_control.py prepare|run (from a fresh repository workspace)')
phase = sys.argv[1]
target = Path(__file__).with_name('prepare_checkpoint_control.py' if phase == 'prepare' else 'run_checkpoint_control.py')
sys.argv = [str(target)]
runpy.run_path(str(target), run_name='__main__')
