#!/usr/bin/env python3
"""Validate external-forward evidence; copy exact bytes only with explicit --write.

Never executes archived helpers, models, compilers, or tests. Historical JSON paths
remain untouched; manifest aliases and reconstruction records explain portability.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import struct


def require(ok, message):
    if not ok:
        raise ValueError(message)


def records(value):
    if isinstance(value, dict):
        if {'path', 'bytes', 'sha256'} <= value.keys():
            yield {k: value[k] for k in ('path', 'bytes', 'sha256')}
        for item in value.values():
            yield from records(item)
    elif isinstance(value, list):
        for item in value:
            yield from records(item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=Path(__file__).with_name('inventory.json'))
    parser.add_argument('--source-root', type=Path, help='Relocate the recorded workspace without rewriting history')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    consumed_inventory = args.inventory.read_bytes()
    executing_source = Path(__file__).read_bytes()
    inventory = json.loads(consumed_inventory)
    old_root = Path(inventory['workspace'])
    root = (args.source_root or old_root).resolve()
    external = old_root / 'matched-external-parity'
    repository = old_root / 'jovovich'
    audit_root = old_root / 'matched-training-audit'
    output = (args.output or root / inventory['output_relative']).absolute()
    require('..' not in output.parts, 'output traversal is not allowed')
    require(not output.exists() and not output.is_symlink(), 'output already exists')
    require(output.parent.is_dir(), 'output parent must already exist')
    for ancestor in (output.parent, *output.parents):
        require(not ancestor.is_symlink(), 'symlink in output path')
    expected, payloads, jsons, aliases, omitted = {}, {}, {}, {}, {}

    def local(path):
        path = Path(path)
        require(path.is_absolute() and '..' not in path.parts, 'invalid recorded path: ' + str(path))
        require(path.is_relative_to(old_root) or str(path) in inventory['host_tool_paths'],
                'reference outside recorded workspace: ' + str(path))
        result = root / path.relative_to(old_root) if path.is_relative_to(old_root) else path
        for part in (result, *result.parents):
            if part == root.parent:
                break
            require(not part.is_symlink(), 'symlink source: ' + str(path))
        return result

    def record(path):
        path = str(path)
        p = local(path)
        before = p.stat()
        require(stat.S_ISREG(before.st_mode), 'not a regular source: ' + path)
        h = hashlib.sha256()
        with p.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                h.update(block)
        after = p.stat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(identity(before) == identity(after), 'source changed during hashing: ' + path)
        return dict(path=path, bytes=after.st_size, sha256=h.hexdigest())

    def bind(item):
        require(isinstance(item['bytes'], int) and item['bytes'] >= 0
                and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'invalid hash binding')
        path = item['path']
        if path in expected:
            require(expected[path] == item, 'conflicting historical binding: ' + path)
        else:
            require(record(path) == item, 'changed binding: ' + path)
            expected[path] = item

    secret_patterns = [
        r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16})\b',
        r'\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b',
        r'https?://[^\s/@:]+:[^\s/@]+@',
        r'(?i)(?:password|access_token|api_key|secret_key)\s*[=:]\s*["\'](?!["\'])[A-Za-z0-9+/=_-]{20,}["\']',
    ]

    def add(path, alias=None):
        path = str(path)
        p = Path(path)
        if path in payloads:
            return
        require(p.suffix not in ('.gguf', '.bin', '.f32', '.a', '.so', '.o', '.pyc')
                and 'build-venv' not in p.parts and not p.is_relative_to(external / 'llama.cpp'),
                'forbidden archive payload: ' + path)
        if alias is None:
            if p.is_relative_to(external):
                alias = 'external/' + p.relative_to(external).as_posix()
            elif p.is_relative_to(audit_root):
                alias = 'audits/' + p.relative_to(audit_root).as_posix()
            elif p.is_relative_to(old_root / 'matched-external-archive'):
                alias = 'collector/' + p.name
            else:
                require(p.is_relative_to(repository), 'unclassified archive payload')
                alias = 'repository-helpers/' + p.relative_to(repository).as_posix()
        dest = Path(alias)
        require(not dest.is_absolute() and '..' not in dest.parts and alias not in aliases.values(),
                'invalid or colliding alias')
        item = record(path)
        bind(item)
        require(item['bytes'] <= 8 * 1024 * 1024, 'unexpected large archive payload: ' + path)
        data = local(path).read_bytes()
        require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
                'source changed while reading: ' + path)
        require(not data.startswith((b'GGUF', b'\x7fELF', b'!<arch>\n', b'MZ', b'PK\x03\x04')),
                'weights/executable/archive disguised as evidence: ' + path)
        if p.suffix != '.dump':
            text = data.decode('utf-8')
            require('\x00' not in text and all(ord(c) >= 32 or c in '\t\r\n' for c in text),
                    'unexpected binary/control bytes: ' + path)
            require(not any(re.search(pattern, text) for pattern in secret_patterns),
                    'credential-like content; do not archive: ' + path)
            if p.suffix == '.json':
                jsons[path] = json.loads(text)
            elif p.suffix == '.jsonl':
                for line in text.splitlines():
                    json.loads(line)
        payloads[path] = data
        aliases[path] = alias

    collector_path = str(old_root / 'matched-external-archive' / Path(__file__).name)
    inventory_path = str(old_root / 'matched-external-archive' / args.inventory.name)
    require(Path(__file__).resolve() == local(collector_path).resolve()
            and args.inventory.resolve() == local(inventory_path).resolve(),
            'executing collector/consumed inventory differ from reviewed locations')
    add(collector_path)
    add(inventory_path)
    require(payloads[collector_path] == executing_source and payloads[inventory_path] == consumed_inventory,
            'collector or consumed inventory changed during startup')
    review_path = inventory['collector_audit']
    add(review_path)
    review = jsons[review_path]
    require(review.get('status') == 'pass' and review.get('collector') == record(collector_path)
            and review.get('inventory') == record(inventory_path),
            'collector/inventory lacks matching independent static review')
    for item in inventory['fixed_files']:
        bind(item)
        add(item['path'])
    for path in inventory['required_files']:
        add(path)
    supplemental = jsons[inventory['supplementary_result_audit']]
    require(supplemental.get('status') == 'pass', 'independent actual-result audit did not pass')

    protocol = jsons[str(external / 'protocol.json')]
    fixed = jsons[str(external / 'fixed-inputs.json')]
    models = {protocol['model']['path']}
    dump_ids, dumps_by_run, auxiliaries = {}, {}, {}

    for run in inventory['runs']:
        plan_path, receipt_path = run['plan'], run['receipt']
        add(plan_path)
        add(receipt_path)
        plan, receipt = jsons[plan_path], jsons[receipt_path]
        plan_record = record(plan_path)
        authorization = jsons[run['authorization']]
        require((authorization.get('plan') == plan_record if run['name'] == 'f32'
                 else authorization.get('execution_plan_sha256') == plan_record['sha256']),
                'authorization covers a different execution plan')
        require(receipt.get('status') == 'completed' and receipt.get('sources_unchanged') is True,
                'unfinished or changed real run: ' + receipt_path)
        require(receipt.get('plan', receipt.get('plan_before')) == plan_record,
                'receipt covers a different execution plan')
        phases = plan['phases']
        require(len(phases) == run['phase_count'] and len(receipt['phases']) == len(phases), 'phase inventory incomplete')
        require(receipt['model_forward_processes_started'] == 4, 'incorrect real forward count')
        require([p['kind'] for p in phases] == run['phase_kinds'], 'unexpected real phase types/order')
        run_dir = Path(plan['output_directory'])
        require(Path(receipt_path) == run_dir / 'receipt.json' and run_dir.is_relative_to(external), 'run path mismatch')
        wanted = {str(run_dir / 'started.json')}
        if run['name'] == 'f32':
            require(receipt.get('plan_after') == plan_record and receipt.get('plan_unchanged') is True
                    and receipt.get('dynamic_unchanged') is True and receipt.get('conversion_processes_started') == 1,
                    'F32 final bindings or conversion count failed')
            models.add(plan['converted_model_path'])
            wanted.update(plan[k] for k in ('native_validation_rows', 'native_validation_stderr', 'validation_receipt'))
            proof = jsons[inventory['auxiliary_provenance']]
            require(proof.get('status') == 'completed_postrun_observation'
                    and proof.get('run_receipt') == record(receipt_path)
                    and proof.get('validated_main_model') == receipt['converted_model'],
                    'auxiliary evidence does not cover completed bound run')
            for entry in proof['auxiliaries']:
                item = entry['binding']
                require(item in inventory['excluded_auxiliary_bindings']
                        and Path(item['path']).parent == run_dir
                        and entry.get('postrun_hash_matches_observation') is True
                        and entry.get('producer_provenance') == 'unresolved', 'unapproved auxiliary exception')
                require(all(item['path'] not in phase['command'] for phase in phases)
                        and all(item['path'] not in {b['path'] for b in actual['input_bindings_before']}
                                for actual in receipt['phases']), 'auxiliary appeared as a phase input')
                bind(item)
                auxiliaries[item['path']] = entry
            require(set(auxiliaries) == {item['path'] for item in inventory['excluded_auxiliary_bindings']}
                    and len(auxiliaries) == 2, 'auxiliary exception set changed')
            wanted.update(auxiliaries)
        dump_count = 0
        for i, (phase, actual) in enumerate(zip(phases, receipt['phases'])):
            require(actual.get('name') == phase['name'] and actual.get('kind') == phase['kind']
                    and actual.get('command') == phase['command'], 'phase identity/command changed')
            require(actual.get('status') == 'completed' and actual.get('exit_code') == 0
                    and actual.get('sources_unchanged') is True
                    and not actual.get('missing_outputs') and not actual.get('missing_or_unhashable_outputs')
                    and actual['input_bindings_before'] == actual['input_bindings_after'], 'incomplete real phase')
            if run['name'] == 'f32':
                require(actual.get('dynamic_unchanged') is True, 'F32 dynamic binding changed')
            own = str(run_dir / f'{i:02d}-{phase["name"]}-receipt.json')
            add(own)
            require(jsons[own] == actual, 'standalone phase receipt differs from aggregate')
            declared = {phase['stdout'], phase['stderr'], *phase['outputs']}
            require({item['path'] for item in actual['artifacts']} == declared, 'phase artifact inventory differs')
            wanted.update(declared | {own})
            if phase['kind'] == 'model_forward':
                require(len(phase['outputs']) == 1 and phase['outputs'][0].endswith('.dump'), 'unexpected forward payload')
                dump_ids[phase['outputs'][0]] = phase['ids']['path']
                dump_count += 1
            elif phase['kind'] == 'metric_comparison':
                add(phase['stdout'])
                metrics = [json.loads(s) for s in payloads[phase['stdout']].decode().splitlines()]
                require(len(metrics) == 2 and [r['prefix_tokens'] for r in metrics] == [444, 447]
                        and all(r['vocabulary'] == 151936 and r['decision_ids'] == [66582, 788] for r in metrics),
                        'incomplete comparison metric captures')
                require(all(math.isfinite(v) for r in metrics for v in r.values() if isinstance(v, float)),
                        'nonfinite comparison metric')
        require(dump_count == 4, 'missing full vocabulary arrays')
        dumps_by_run[run['name']] = dump_count
        actual_artifacts = {item['path'] for item in receipt['artifacts']}
        require(actual_artifacts == wanted, 'unexpected/missing run files in receipt')
        disk_files = {str(run_dir / p.relative_to(local(run_dir))) for p in local(run_dir).rglob('*') if p.is_file()}
        require(disk_files == wanted | {receipt_path}, 'unrecorded file in real run directory')
        for item in receipt['artifacts']:
            bind(item)
            if item['path'] not in models and item['path'] not in auxiliaries:
                add(item['path'])

    f32_plan = jsons[inventory['runs'][1]['plan']]
    conversion = jsons[f32_plan['validation_receipt']]
    f32_receipt = jsons[inventory['runs'][1]['receipt']]
    f32_summary = jsons[str(external / 'alignment/summary.json')]
    require(f32_summary.get('status') == 'completed', 'F32 summary is unfinished')
    require(record(inventory['runs'][1]['receipt']) in list(records(f32_summary)), 'F32 summary does not bind completed receipt')
    require(conversion.get('status') == 'completed' and conversion.get('native_exit_code') == 0
            and all(conversion.get(key) is True for key in ('every_tensor_exact', 'all_finite', 'semantic_metadata_exact'))
            and conversion.get('base') == protocol['model'] and conversion.get('metadata_keys_checked') == 26
            and conversion.get('converted') == f32_receipt['converted_model']
            and conversion.get('expected_byte_extent') == 2526617472
            and conversion.get('metadata_changes') == [dict(key='general.file_type', original_hex='0400000007000000', converted_hex='0400000000000000')],
            'F32 independent validation incomplete')
    tensor_rows = [json.loads(s) for s in payloads[f32_plan['native_validation_rows']].decode().splitlines()]
    require(all(path not in conversion['native_command'] for path in auxiliaries),
            'auxiliary appeared in independent tensor-validation argv')
    tensors = conversion.get('tensors', [])
    require(len(tensors) == len(tensor_rows) == 291 and len({r['name'] for r in tensors}) == 291
            and {r['name'] for r in tensors} == {r['name'] for r in tensor_rows}
            and sum(r['elements'] for r in tensor_rows) == 630167424
            and all(r.get('exact_float32_bytes') is True and r.get('all_finite') is True for r in tensor_rows),
            'F32 tensor coverage incomplete')

    for path, ids_path in dump_ids.items():
        data = payloads[path]
        require(len(data) == 1217308 and struct.unpack_from('<6I', data) == (0x324c564a, 2, 1, 151936, 2, 447),
                'unexpected binary logit format: ' + path)
        ids = tuple(map(int, payloads[ids_path].decode().split()))
        require(len(ids) == 447 and struct.unpack_from('<447I', data, 24) == ids, 'dump fixed IDs differ')
        offset = 24 + 447 * 4
        for position in (444, 447):
            require(struct.unpack_from('<I', data, offset)[0] == position, 'dump capture position differs')
            offset += 4
            require(all(math.isfinite(x[0]) for x in struct.iter_unpack('<f', data[offset:offset + 151936 * 4])),
                    'nonfinite logit payload')
            offset += 151936 * 4
        require(offset == len(data), 'trailing logit payload')
    require({p for p in payloads if p.endswith('.dump')} == set(dump_ids), 'unapproved binary payload')

    # Verify all retained structured hash bindings, including intentionally omitted
    # models/binaries/dependencies. Synthetic fixture payloads remain references only.
    fixture_roots = [external / name for name in inventory['excluded_fixture_directories']]
    synthetic_refs = {}
    for document in jsons.values():
        for item in records(document):
            if item['path'] not in payloads and any(Path(item['path']).is_relative_to(p) for p in fixture_roots):
                # Mutation/missing-file tests deliberately record several historical
                # hashes at one path. Preserve every record; never pretend it is a
                # still-live binding or copy the mutable synthetic payload.
                synthetic_refs[(item['path'], item['sha256'], item['bytes'])] = dict(item,
                    kind='omitted_synthetic_fixture', reconstruction='Reproduce with archived checker; recorded pre/post versions may intentionally differ or be absent.')
            else:
                bind(item)
    binaries = {item['path'] for item in protocol['binaries'].values()}
    proposal = jsons[str(external / 'alignment/proposed-plan.json')]
    binaries.update(item['path'] for item in proposal['binaries'].values())
    binaries.update(item['path'] for item in proposal['linked_reference_libraries'])
    for path, item in expected.items():
        if path in aliases:
            continue
        p = Path(path)
        ref = dict(item)
        if path in models:
            ref.update(kind='omitted_model_weights', reconstruction='Match this SHA256; original model provenance is in repository README. Expanded F32 is reconstructed by archived alignment source and frozen execution plan.')
        elif path in auxiliaries:
            ref.update(kind='omitted_undeclared_non_input_auxiliary_binary', producer_provenance='unresolved',
                       observation=auxiliaries[path], evidence_archive_path=aliases[inventory['auxiliary_provenance']],
                       reconstruction='Not a declared phase input or required for reproduction. Preserve this historical record; origin and reconstruction recipe are unresolved. No producer or tensor-layout claim is made.')
        elif path in binaries:
            ref.update(kind='omitted_compiled_artifact', reconstruction='Rebuild using archived sources, build-commands.json, CMake/configuration receipts, and alignment/proposed-plan.json; verify recorded SHA256 if reproducing identical toolchain bytes.')
        elif path in inventory['host_tool_paths']:
            ref.update(kind='omitted_host_tool', reconstruction='Host executable recorded by frozen plan; provision an equivalent toolchain separately. Original bytes are identified by this digest, not distributed.')
        elif any(p.is_relative_to(prefix) for prefix in fixture_roots):
            ref.update(kind='omitted_synthetic_fixture', reconstruction='Reproduce only with the archived checker; this fixture is not real model evidence.')
        elif p.is_relative_to(external / 'llama.cpp'):
            ref.update(kind='pinned_upstream_source', repository='https://github.com/ggml-org/llama.cpp', commit=protocol['reference_commit'], relative_path=p.relative_to(external / 'llama.cpp').as_posix())
        elif p.is_relative_to(repository / 'deps/notorch'):
            ref.update(kind='pinned_dependency_source', repository='https://github.com/ariannamethod/notorch', commit=protocol['notorch_pin'], relative_path=p.relative_to(repository / 'deps/notorch').as_posix())
        elif p.is_relative_to(repository):
            ref.update(kind='repository_reference', repository='https://github.com/ariannamethod/jovovich', relative_path=p.relative_to(repository).as_posix(), reconstruction='Resolve at the published repository path; verify this recorded digest. Historical paths remain literal.')
        else:
            raise ValueError('unresolved evidence reference; add explicit inventory or reconstruction: ' + path)
        omitted[path] = ref

    # All reads must still agree immediately before writing; the same check follows
    # copying. A failure leaves a partial archive without manifest, never overwrites.
    for item in expected.values():
        require(record(item['path']) == item, 'binding changed before collection: ' + item['path'])
    manifest = dict(schema_version=1, status='validated', created_utc=datetime.now(timezone.utc).isoformat(),
                    original_workspace=str(old_root), bytes_preserved=True, history_rewritten=False,
                    scope='External original-Q8 and verified-F32 forward controls only; no training or review evaluation.',
                    files=[dict(expected[p], archive_path=aliases[p]) for p in sorted(payloads)],
                    references=[omitted[p] for p in sorted(omitted)] + [synthetic_refs[p] for p in sorted(synthetic_refs)],
                    cross_archive_resolution='For any literal source path cited by another archive, use this manifest files[].path -> archive_path or references[].reconstruction. Do not edit archived records.',
                    dump_counts=dumps_by_run, dump_bytes=sum(len(payloads[p]) for p in dump_ids),
                    exclusions=inventory['exclusions'])
    if args.write:
        output.mkdir(exist_ok=False)
        for path, data in payloads.items():
            target = output / aliases[path]
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            require(hashlib.sha256(target.read_bytes()).hexdigest() == expected[path]['sha256'], 'copied bytes differ')
        for item in expected.values():
            require(record(item['path']) == item, 'binding changed during collection: ' + item['path'])
        manifest['status'] = 'collected'
        with (output / 'manifest.json').open('x') as stream:
            json.dump(manifest, stream, indent=2)
            stream.write('\n')
    print(json.dumps(dict(status=manifest['status'], output=str(output), files=len(payloads),
                          bytes=sum(map(len, payloads.values())), references=len(omitted),
                          dump_counts=dumps_by_run, dump_bytes=manifest['dump_bytes'], wrote=args.write)))


if __name__ == '__main__':
    main()
