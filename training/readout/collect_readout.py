#!/usr/bin/env python3
"""Archive a completed frozen readout run byte-for-byte, without model weights.

Repository source files stay in their normal locations and receive manifest hash
bindings. Prepared prompts, frozen masks, feature binaries, scalar diagnostics,
predictions and source helpers outside the repository are retained as evidence.
This copies only after the completed-run and native-fit gates have passed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from run_readout import file_record, require, save_new, verify


def checked(path):
    data = path.read_bytes()
    require(not re.search(rb'hf_[A-Za-z0-9]{20,}', data), 'credential-like input: ' + str(path))
    require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data), 'private key-like input: ' + str(path))
    return data


def jsonl(path):
    data = checked(path)
    require(data.endswith(b'\n'), 'incomplete JSONL: ' + str(path))
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def validate_fits(path, width, normalization):
    rows = jsonl(path)
    require(rows[0]['type'] == 'configuration', 'missing initial native configuration')
    config = rows[0]
    for key, value in {'rows':52, 'width':width, 'families':20, 'pairs':26, 'permutations':99,
                       'normalization':normalization, 'lambda':0.01, 'interpolation_lambda':1e-8,
                       'gradient_tolerance':1e-8, 'max_iterations':100}.items():
        require(config[key] == value, 'native configuration changed: ' + key)
    fits = [r for r in rows if r['type'] == 'fit']
    norms = [r for r in rows if r['type'] == 'normalization']
    require(len(rows) == 2025 and len(fits) == 2002 and len(norms) == 21, 'incomplete native records')
    require(rows[-1] == {'type':'completion','fits':2002,'failed_fits':0,'all_converged':True}, 'native fit completion failed')
    expected = {('heldout', permutation, fold) for fold in range(20) for permutation in range(-1,99)}
    expected |= {('interpolation', -1, -1), ('interpolation', 0, -1)}
    observed = {(r['mode'],r['permutation'],r['heldout_family']) for r in fits}
    require(observed == expected, 'native fit identity coverage mismatch')
    require({r['heldout_family'] for r in norms} == set(range(-1,20)), 'normalization fold coverage mismatch')
    for r in fits:
        require(r['converged'] is True and r['gradient_inf'] <= 1e-8, 'uncertified native fit')
        require(not {'weights','intercept','bias','coefficients'} & set(r), 'fitted parameters must remain unexported')
    return {'fits':len(fits),'normalizations':len(norms),'all_converged':True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path)
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--run-dir', required=True, type=Path)
    p.add_argument('--plan', required=True, type=Path)
    p.add_argument('--summary', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--evidence', action='append', type=Path, default=[])
    p.add_argument('--failed-attempt', type=Path, help='Immutable snapshot directory with its own manifest; include below failed-attempt-1/')
    args = p.parse_args()
    root, ref, run, out = (v.resolve() for v in (args.repo,args.reference,args.run_dir,args.output))
    require(not out.exists(), 'archive destination already exists')
    plan = json.loads(args.plan.read_bytes())
    require(plan['protocol_frozen'] is True, 'unfrozen plan')
    bindings = verify(plan['frozen_inputs'], root)
    receipt = json.loads((run/'readout-run.json').read_bytes())
    require(receipt['status'] == 'completed' and receipt['all_frozen_inputs_unchanged'] is True, 'run was not completed unchanged')
    require(receipt['plan'] == file_record(args.plan.resolve()), 'receipt binds another plan')
    require(len(receipt['phases']) == len(plan['execution']['phases']) == 6, 'phase coverage mismatch')
    for actual, intended in zip(receipt['phases'],plan['execution']['phases']):
        require(actual['name'] == intended['name'] and actual['argv'] == intended['argv'] and actual['returncode'] == 0, 'phase execution mismatch')
        for record in [actual['stdout'],actual['stderr'],*actual['created_files']]:
            require(file_record(Path(record['path'])) == record, 'run output changed since completion')
    fit_checks = {'state':validate_fits(run/'state-fits.jsonl',896,'centered-rms'),
                  'nuisance':validate_fits(run/'nuisance-fit-fits.jsonl',7,'per-feature-rms')}
    for filename,width in [('readout-features.bin',896),('readout-nuisance.bin',7)]:
        data=checked(run/filename)
        require(data[:8] == b'JVRF1\0\0\0' and struct.unpack('<II',data[8:16]) == (52,width), 'feature header mismatch')
        require(len(data) == 16+52*width*4, 'feature file length mismatch')
    traces=jsonl(run/'extract.stdout.jsonl')
    require(len(traces)==52 and [r['row'] for r in traces]==list(range(52)), 'extraction row coverage mismatch')
    require(all(r['prefix_ids']==[4913,3903,819] and r['capture_position']==r['prompt_tokens']+2 and r['input_tokens']==len(r['input_ids'])==r['prompt_tokens']+3 and r['input_ids'][-3:]==[4913,3903,819] for r in traces),'causal trace mismatch')
    parity=jsonl(run/'parity.stdout.jsonl')
    require(len(parity)==2 and all(all(r[k]['pass'] for k in ['full_trainer_cache','changed_future','original_residual_reconstruction']) for r in parity),'native parity gate failed')
    # A summary is mandatory, but its domain calculations remain those of the
    # separately frozen summarizer; this collector does not manufacture scores.
    planned_summary=next(p for p in plan['execution']['phases'] if p['name']=='summary')
    require(len(planned_summary['creates'])==1 and args.summary.resolve()==(root/planned_summary['creates'][0]).resolve(), 'summary argument differs from the completed planned summary')
    summary=json.loads(checked(args.summary))
    evidence, origins, source_records = {}, {}, {}
    def collect(path,name=None):
        path=path.resolve(); name=name or path.name
        relative=Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts and name not in ('','.','manifest.json'), 'invalid archive relative path')
        data=checked(path)
        if name in evidence:
            require(evidence[name]==data, 'archive basename collision: '+name)
            return
        evidence[name]=data;origins[name]=str(path)
    for path in sorted(run.iterdir()):
        require(path.is_file(), 'unexpected nested run artifact: '+str(path))
        collect(path)
    collect(args.plan,'plan.json');collect(args.summary)
    for name, record in bindings.items():
        path=Path(record['path'])
        if path.is_relative_to(run):
            # Prepared inputs may live in a scratch run outside both the repo
            # and the maintained helper directory. Reuse the exact bytes
            # already collected above; collect() checks basename collisions.
            collect(path)
        elif path.is_relative_to(root):
            relative=path.relative_to(root).as_posix()
            if relative.startswith(('models/','build/')):
                continue
            source_records[relative]={'sha256':record['sha256'],'bytes':record['bytes']}
        elif path.is_relative_to(ref):
            collect(path)
        elif name.startswith('gate:'):
            collect(path)
        else:
            raise ValueError('unclassified external frozen input: '+str(path))
    collect(Path(__file__))
    for path in args.evidence:
        collect(path)
    failed_executable_omissions=[]
    if args.failed_attempt:
        failed=args.failed_attempt.resolve()
        historical=json.loads(checked(failed/'manifest.json'))
        require(historical['run_status']=='failed' and historical['feature_extraction_started'] is False and historical['classifier_fits_started'] is False, 'failed attempt classification mismatch')
        require(historical['plan_sha256'] != receipt['plan']['sha256'], 'failed and successful plans must be separate')
        for name,binding in historical['files'].items():
            path=(failed/name).resolve()
            require(path.is_relative_to(failed), 'failed attempt path escapes snapshot')
            record=file_record(path)
            require(record['sha256']==binding['sha256'] and record['bytes']==binding['bytes'], 'failed attempt evidence changed')
            if name.startswith('repository/build/'):
                failed_executable_omissions.append({'snapshot_path':name,'sha256':binding['sha256'],'bytes':binding['bytes'],'reason':'Compiled executable retained in the local original snapshot only. Public archive retains source, build configuration, exact executable hash and failure receipts; rebuilding may change binary bytes.'})
            else:
                collect(path,'failed-attempt-1/'+name)
        collect(failed/'manifest.json','failed-attempt-1/manifest.json')
    # All validation precedes directory creation, preventing a half-validated
    # archive from being mistaken for a publishable completed result.
    out.mkdir(parents=True,exist_ok=False)
    for name,data in evidence.items():
        (out/name).parent.mkdir(parents=True,exist_ok=True)
        with (out/name).open('xb') as f:f.write(data)
    manifest={'schema_version':1,'parent_commit':plan['parent_commit'],
              'status':'Completed frozen-state binary diagnostic; no model weight update or runtime promotion',
              'source_files':source_records,
              'evidence':{name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'runtime_path':origins[name]} for name,data in sorted(evidence.items())},
              'model_sha256':plan['model']['base_sha256'],'notorch_commit':plan['model']['notorch_pin'],
              'native_fit_validation':fit_checks,'fitted_parameters_exported':False,'summary_evidence':args.summary.name,'failed_attempt_executable_omissions':failed_executable_omissions,
              'evidence_bytes':'Copied byte-for-byte; original absolute paths and source bindings are preserved.',
              'reproduction':'Use reproduction.json with a fresh scratch run. Historical receipts are never overwritten; compiler and CPU differences may change exact binaries and floating-point outputs.'}
    save_new(out/'manifest.json',manifest)
    for name,data in evidence.items():
        require((out/name).read_bytes()==data,'post-copy evidence mismatch')
    print(json.dumps({'archive':str(out),'files':len(evidence)+1,'manifest':file_record(out/'manifest.json')}))


if __name__ == '__main__':
    main()
