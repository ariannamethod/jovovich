#!/usr/bin/env python3
"""Bind the reviewed readout design to exact inputs and commands before execution.

Call only after the independent implementation audit and numerical tests pass.
This creates an immutable new plan; it does not execute inference or fitting.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from run_readout import file_record, require, save_new


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--draft', required=True, type=Path)
    p.add_argument('--run-dir', required=True, type=Path)
    p.add_argument('--sft', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--evidence', action='append', type=Path, default=[])
    args = p.parse_args()
    root, ref, run = (v.resolve() for v in (args.repo, args.reference, args.run_dir))
    plan = json.loads(args.draft.resolve().read_bytes())
    require(plan['protocol_frozen'] is False, 'input is not the unfrozen draft')
    require(args.evidence, 'review and numerical evidence must be supplied explicitly')
    require(run.is_dir(), 'prepared run directory missing')
    require(not (run/'readout-run.json').exists(), 'run has already been attempted')
    frozen = {}
    def bind(name, path):
        require(name not in frozen, 'duplicate binding: ' + name)
        frozen[name] = file_record(path.resolve())
    for name in ('prepare_readout.py', 'run_readout.py', Path(__file__).name, 'summarize_readout.py'):
        bind('helper:'+name, ref/name)
    bind('helper:'+args.draft.name, args.draft)
    for name in ('readout-input.bin','readout-masks.json','readout-masks.txt','readout-metadata.txt','readout-preparation.json','readout-rows.json'):
        bind('input:'+name, run/name)
    for name in ('jovovich-extract-readout','jovovich-probe-readout','jovovich-readout-fit'):
        bind('binary:'+name, root/'build'/name)
    for name in ('Makefile','model.json','training/train_mlp.c','training/extract_readout.c','training/probe_readout.c','training/readout_fit.c','training/prepare.py','training/sft_review_v4.jsonl','src/infer.c','test/readout_extract.c','test/readout.c','test/readout_fit.test.mjs'):
        bind('source:'+name, root/name)
    # Bind the substrate files actually used by the native build. The pin and
    # clean status additionally preserve the dependency's version identity.
    native = ('notorch.c','notorch.h','notorch_simd.h','gguf.c','gguf.h','harness/runtime.c','harness/runtime.h','harness/arch_llama.c','harness/arch.h','harness/arch_models.h','examples/bpe.c','examples/bpe.h','examples/unicode_numbers.h')
    for name in native:
        bind('notorch:'+name, root/'deps/notorch'/name)
    for i, path in enumerate(args.evidence):
        bind('gate:'+str(i)+':'+path.name, path)
    bind('base-model', root/'models/base-qwen.gguf')
    require(frozen['base-model']['sha256'] == plan['model']['base_sha256'], 'wrong base model')
    bind('parity-sft', args.sft)
    pin = subprocess.check_output(['git','-C',str(root/'deps/notorch'),'rev-parse','HEAD'], text=True).strip()
    require(pin == plan['model']['notorch_pin'], 'notorch pin differs from design')
    require(not subprocess.check_output(['git','-C',str(root/'deps/notorch'),'status','--porcelain'], text=True).strip(), 'notorch working tree is modified')
    phases = []
    def phase(name, argv, creates=()):
        phases.append({'name':name, 'argv':[str(x) for x in argv], 'stdout':str(run/(name+'.stdout.jsonl')), 'stderr':str(run/(name+'.stderr.txt')), 'creates':[str(run/x) for x in creates]})
    base, prompts = root/'models/base-qwen.gguf', run/'readout-input.bin'
    phase('parity', [root/'build/jovovich-probe-readout',base,prompts,args.sft.resolve(),'4'])
    phase('extract', [root/'build/jovovich-extract-readout',base,prompts,run/'readout-features.bin','4'], ['readout-features.bin'])
    phase('nuisance', ['python3',ref/'prepare_readout.py','--out',run,'--trace',run/'extract.stdout.jsonl'], ['readout-nuisance.bin','readout-nuisance-metadata.txt','readout-nuisance.json'])
    for name, matrix, metadata, normalization in [('state','readout-features.bin','readout-metadata.txt','centered-rms'),('nuisance-fit','readout-nuisance.bin','readout-nuisance-metadata.txt','per-feature-rms')]:
        output = name+'-fits.jsonl'
        phase(name,[root/'build/jovovich-readout-fit','--matrix',run/matrix,'--metadata',run/metadata,'--masks',run/'readout-masks.txt','--output',run/output,'--normalization',normalization,'--lambda','0.01','--interpolation-lambda','1e-8','--gradient-tolerance','1e-8','--max-iterations','100'],[output])
    phase('summary', ['python3',ref/'summarize_readout.py','--z',run/'state-fits.jsonl','--nuisance',run/'nuisance-fit-fits.jsonl','--rows',run/'readout-rows.json','--masks-json',run/'readout-masks.json','--output',run/'readout-summary.json'], ['readout-summary.json'])
    plan.update({'status':'FROZEN before any model feature extraction or classifier fitting', 'protocol_frozen':True, 'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
                 'parent_commit':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
                 'frozen_inputs':frozen,
                 'execution':{'cwd':str(root),'environment':{'NT_NO_I8':'1','NT_QMV_THREADS':'4','NT_ATTN_THREADS':'4','NT_SIMD_THREADS':'4'},'phases':phases},
                 'execution_record':'Run separately with run_readout.py --plan THIS_FILE --output-dir the prepared run directory. Every source/model/input is hash-checked before and after each phase. Preserve this file byte-for-byte.'})
    save_new(args.output.resolve(),plan)
    print(json.dumps(file_record(args.output.resolve())))


if __name__ == '__main__':
    main()
