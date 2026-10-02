"""Freeze exact-weight alignment commands without executing model operations."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
spec = importlib.util.spec_from_file_location('alignment_controller', HERE / 'run_alignment.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
record, save, require = controller.record, controller.save, controller.require


def main():
    proposal_path = HERE / 'proposed-plan.json'
    require(record(proposal_path)['sha256'] == '7fda2c239d1a6eb55b7b14888d592deefbe871ffa50c480312d242ae1b8f7cf4',
            'audited alignment preparation changed')
    proposal = json.loads(proposal_path.read_text())
    original_plan = json.loads((PARENT / 'execution-plan-v2.json').read_text())
    protocol = json.loads((PARENT / 'protocol.json').read_text())
    q8_receipt_path = PARENT / 'q8-control-1/receipt.json'
    require(record(q8_receipt_path)['sha256'] == '20ce067bbd31302ad53d8bbdeb4550c15355fb81d768483016ef867d5c6cbdd7',
            'completed original-Q8 evidence changed')
    q8_receipt = json.loads(q8_receipt_path.read_text())
    require(q8_receipt['status'] == 'completed' and q8_receipt['sources_unchanged'] is True,
            'original-Q8 check did not finish successfully')
    summary_path = PARENT / 'q8-summary.json'
    require(record(summary_path)['sha256'] == 'c17a4591afc5f4e240dbdcb69c651d98bfbb697992ba926521e9bd7df8707e41',
            'original-Q8 numeric screening summary changed')
    summary = json.loads(summary_path.read_text())
    require(summary['status'] == 'completed' and summary['alignment_screening_triggered'] is True,
            'alignment follow-up lacks measured screening trigger')
    output = HERE / 'run-1'
    require(not output.exists(), 'alignment output directory already exists')
    nice, python = str(Path(shutil.which('nice')).resolve()), str(Path(sys.executable).resolve())
    converted = output / 'original-base-expanded-f32.gguf'
    validation = output / 'validation'
    native_rows, native_stderr = validation / 'native-values.jsonl', validation / 'native-values.stderr'
    audit_dir = PARENT.parent / 'matched-training-audit'
    audit_paths = [audit_dir / name for name in ('external-forward-preparation-independent-audit.json',
                    'external-execution-v2-independent-audit.json', 'f32-alignment-preparation-independent-audit.json')]
    existing_sources = {item['path']: item for item in proposal['sources']}
    verifier_script = existing_sources[str(HERE / 'verify_alignment.py')]
    parser_binding = next(item for item in proposal['sources'] if item['path'].endswith('/check_convergence_export.py'))
    prior_dumps = {label: record(PARENT / 'q8-control-1' / (label + '-notorch.dump')) for label in ('concern', 'clean')}
    all_bindings = [*original_plan['bindings'], proposal['original_protocol'], proposal['original_execution'],
                    protocol['build']['cmake_cache'], *protocol['build']['cmake_flags'].values(),
                    *proposal['sources'], *proposal['binaries'].values(), *proposal['linked_reference_libraries'],
                    record(proposal_path), record(q8_receipt_path), record(summary_path),
                    *map(record, audit_paths), *prior_dumps.values(), record(HERE / 'run_alignment.py'),
                    record(__file__), record(HERE / 'check_execution_boundary.py'),
                    record(HERE / 'execution-boundary-check.json'), record(nice), record(python)]
    unique = {}
    for item in all_bindings:
        require(item['path'] not in unique or item == unique[item['path']], 'conflicting source binding')
        unique[item['path']] = item
    bindings = list(unique.values())
    require(controller.snapshot(bindings) == bindings, 'bound alignment source changed')
    phases = []

    def phase(name, kind, command, outputs, **extra):
        phases.append(dict(name=name, kind=kind, command=command,
                           stdout=str(output / (name + '.stdout.jsonl')),
                           stderr=str(output / (name + '.stderr')), outputs=list(map(str, outputs)), **extra))

    phase('convert-exact-f32', 'conversion', [nice, '-n', '15', proposal['binaries']['convert-f32']['path'],
            protocol['model']['path'], str(converted)], [converted])
    phase('verify-exact-f32', 'independent_validation', [nice, '-n', '15', python, '-E', verifier_script['path'],
            '--base', protocol['model']['path'], '--converted', str(converted),
            '--native-verifier', proposal['binaries']['verify-tensor-values']['path'],
            '--output-dir', str(validation)], [validation / 'validation.json', native_rows, native_stderr])
    for label, case in zip(('concern', 'clean'), protocol['cases']):
        require(case['id'] == 'allocation-null-guard-deletion-' + label, 'fixed pair changed')
        controller.verify_dump(prior_dumps[label]['path'], case['ids']['path'])
        dumps = {}
        for engine in ('notorch', 'llama'):
            name = label + '-' + engine + '-f32'
            dump = output / (name + '.dump')
            dumps[engine] = str(dump)
            phase(name, 'model_forward', [nice, '-n', '15', protocol['binaries'][engine]['path'],
                  str(converted), case['ids']['path'], str(dump)], [dump], ids=case['ids'],
                  model_binding='created_f32_hash_then_all_tensor_validation_required')
        for kind, first, second in (
                ('native-packing', prior_dumps[label]['path'], dumps['notorch']),
                ('aligned-engine', dumps['notorch'], dumps['llama'])):
            name = label + '-' + kind + '-comparison'
            phase(name, 'metric_comparison', [nice, '-n', '15', proposal['binaries']['compare-alignment-logits']['path'],
                  first, second], [], ids=case['ids'], comparison_kind=kind, comparison_dumps=[first, second])
    plan = dict(schema_version=1, status='ready_requires_root_execution_decision',
                scientific_protocol=record(PARENT / 'protocol.json'), alignment_proposal=record(proposal_path),
                prior_execution_plan=record(PARENT / 'execution-plan-v2.json'), prior_receipt=record(q8_receipt_path),
                screening_evidence=record(summary_path), independent_preparation_audits=list(map(record, audit_paths)),
                controller=record(HERE / 'run_alignment.py'), preparer=record(__file__),
                execution_boundary_check=record(HERE / 'execution-boundary-check.json'),
                working_directory=str(HERE), output_directory=str(output), bindings=bindings,
                original_model=protocol['model'], converted_model_path=str(converted),
                validation_receipt=str(validation / 'validation.json'),
                native_validation_rows=str(native_rows), native_validation_stderr=str(native_stderr),
                validation_bindings=dict(verifier=proposal['binaries']['verify-tensor-values'], script=verifier_script,
                                         parser=parser_binding),
                environment=original_plan['environment'],
                environment_cleanup='Remove every inherited NT_* variable before exact fixed overrides.',
                phases=phases, new_model_forward_processes=4, conversion_processes=1,
                comparison_processes=4, serial=True, nice=15, threads=1,
                created_model_gate='Record converted bytes/hash after native conversion; require all291 tensors and630167424 float32 values bitwise exact plus all metadata/layout checks before any forward. Rehash converted model and validation evidence before/after every later phase.',
                early_failure_contract='Reserve the explicit fresh output directory before plan read/hash/binding checks. Retain actual before/after records, missing/unhashable records, child streams/status/resources and partial outputs on failure. Refuse an existing output directory without modifying it.',
                resource_estimate=dict(converted_weight_bytes=2526617472, new_logit_dumps=4,
                    bytes_per_dump=1217308, new_logit_dump_bytes=4869232,
                    retained_weight_temporary=True, simultaneous_children=1,
                    estimated_peak_rss_bytes=3600000000,
                    estimate_note='Conservative allowance for original+expanded mmaps during validation; forwards run serially. Root must recheck cgroup memory, available reclaimable cache and free disk before authorization.'),
                interpretation='No arbitrary aggregate tolerance implies a defect. Compare native Q8 versus native exact-F32 separately from native-F32 versus llama-F32. Preserve all logits, scalar differences, top ranks, unrounded three-way decision-margin signs. No selection input changes.',
                explicit_execution_gate='Requires independent audit of this execution plan/controller and a fresh root execution go. Preparing this JSON does not authorize conversion or forwards.')
    save(HERE / 'execution-plan.json', plan)
    print(json.dumps(dict(plan=record(HERE / 'execution-plan.json'), controller=plan['controller'],
                          frozen_bindings=len(bindings), phases=len(phases), conversions=0, model_forwards=0)))


if __name__ == '__main__':
    main()
