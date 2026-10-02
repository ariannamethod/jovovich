"""Read saved evidence only; independently recompute every saved logit metric."""
import hashlib
import heapq
import importlib.util
import json
import math
import mmap
from pathlib import Path
import struct

ROOT = Path('/workspace/scratch/ec5ba60588d8')
EXTERNAL = ROOT / 'matched-external-parity'
ALIGNMENT = EXTERNAL / 'alignment'
AUDIT = ROOT / 'matched-training-audit'
CACHE = {}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def record(path):
    path = Path(path)
    before = path.stat()
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'file changed during hashing')
    return dict(path=str(path), bytes=after.st_size, sha256=h.hexdigest())

def bind(item):
    path = item['path']
    if path not in CACHE:
        CACHE[path] = record(path)
    require(CACHE[path] == item, 'changed evidence: ' + path)

def document(path):
    return json.loads(Path(path).read_text())

def sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0

def typed_metadata(data):
    pos = 0
    def take(n):
        nonlocal pos
        require(0 <= n <= len(data)-pos, 'truncated metadata')
        result = data[pos:pos+n]
        pos += n
        return result
    def integer(kind):
        return struct.unpack('<'+kind, take(struct.calcsize('<'+kind)))[0]
    def string():
        return take(integer('Q'))
    def skip(kind):
        sizes = {0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}
        if kind in sizes:
            take(sizes[kind])
        elif kind == 8:
            string()
        elif kind == 9:
            item, count = integer('I'), integer('Q')
            require(item != 9, 'unsupported nested array')
            for _ in range(count):
                skip(item)
        else:
            raise ValueError('unsupported metadata type')
    require(take(4) == b'GGUF' and integer('I') == 3, 'wrong metadata header')
    require(integer('Q') == 291, 'metadata tensor count differs')
    count = integer('Q')
    result = {}
    for _ in range(count):
        key = string().decode()
        require(key not in result, 'duplicate metadata key')
        begin = pos
        skip(integer('I'))
        result[key] = data[begin:pos]
    return result

def read_dump(path, ids):
    data = Path(path).read_bytes()
    require(len(data) == 1217308, 'dump extent differs')
    require(struct.unpack_from('<6I', data) == (0x324c564a, 2, 1, 151936, 2, 447), 'dump header differs')
    require(list(struct.unpack_from('<447I', data, 24)) == ids, 'wrong-case token IDs')
    offset, rows = 24 + 447 * 4, []
    for pos in (444, 447):
        require(struct.unpack_from('<I', data, offset)[0] == pos, 'capture position differs')
        offset += 4
        values = struct.unpack_from('<151936f', data, offset)
        bits = struct.unpack_from('<151936I', data, offset)
        require(all(math.isfinite(v) for v in values), 'nonfinite saved logit')
        rows.append((values, bits))
        offset += 151936 * 4
    require(offset == len(data), 'trailing bytes')
    return rows

def metrics(first, second):
    x, xb = first
    y, yb = second
    n = len(x)
    differences = [float(a) - b for a, b in zip(x, y)]
    absdiff = [abs(d) for d in differences]
    maxid = max(range(n), key=absdiff.__getitem__)
    tx = heapq.nsmallest(10, range(n), key=lambda i: (-x[i], i))
    ty = heapq.nsmallest(10, range(n), key=lambda i: (-y[i], i))
    error2 = math.fsum(d*d for d in differences)
    reference2 = math.fsum(float(v)*v for v in y)
    return dict(different_float32_values=sum(a != b for a, b in zip(xb, yb)),
        max_abs=absdiff[maxid], max_abs_token_id=maxid, reference_max_abs=max(map(abs, y)),
        relative_l2=math.sqrt(error2 / max(reference2, 1e-300)),
        rmse=math.sqrt(error2/n), mean_abs=math.fsum(absdiff)/n,
        first_argmax=tx[0], second_argmax=ty[0], argmax_agree=tx[0] == ty[0],
        first_top_margin=float(x[tx[0]])-x[tx[1]], second_top_margin=float(y[ty[0]])-y[ty[1]],
        first_concern_minus_clean=float(x[66582])-x[788],
        second_concern_minus_clean=float(y[66582])-y[788],
        first_top10=[dict(id=i, logit=x[i]) for i in tx],
        second_top10=[dict(id=i, logit=y[i]) for i in ty])

def compare_saved(saved, actual, q8):
    for key, value in actual.items():
        stored_key = key.replace('first_', 'notorch_').replace('second_', 'llama_') if q8 else key
        stored = saved[stored_key]
        if key.endswith('_top10'):
            require([x['id'] for x in stored] == [x['id'] for x in value], 'top10 ranks differ')
            require(all(float(format(b['logit'], '.9g')) == a['logit'] for a, b in zip(stored, value)),
                    'printed top10 logits differ')
        elif isinstance(value, float):
            # C uses sequential double sums; fsum is independent and slightly more accurate.
            require(math.isclose(stored, value, rel_tol=5e-12, abs_tol=1e-14),
                    'saved scalar differs from full-vector recomputation: ' + key)
        else:
            require(stored == value, 'saved discrete result differs: ' + key)

def main():
    protocol = document(EXTERNAL/'protocol.json')
    runs = [dict(name='q8', plan=EXTERNAL/'execution-plan-v2.json', receipt=EXTERNAL/'q8-control-1/receipt.json'),
            dict(name='f32', plan=ALIGNMENT/'execution-plan.json', receipt=ALIGNMENT/'run-1/receipt.json')]
    dumps, comparisons, run_checks = {}, [], []
    for run in runs:
        plan, receipt = document(run['plan']), document(run['receipt'])
        require(receipt['status'] == 'completed' and receipt['sources_unchanged'], 'run incomplete')
        require(receipt.get('plan', receipt.get('plan_before')) == record(run['plan']), 'plan link differs')
        require(receipt['model_forward_processes_started'] == 4, 'forward coverage differs')
        for item in plan['bindings']:
            bind(item)
        for item in receipt['artifacts']:
            bind(item)
        require(len(receipt['phases']) == len(plan['phases']) == (6 if run['name'] == 'q8' else 10),
                'phase coverage differs')
        if run['name'] == 'f32':
            require(receipt['plan_unchanged'] and receipt['dynamic_unchanged'] and
                    receipt['conversion_processes_started'] == 1, 'F32 invariance differs')
            require(receipt['plan_before'] == receipt['plan_after'], 'F32 plan changed')
            for item in receipt['dynamic_bindings_after']:
                bind(item)
        for index, (phase, actual) in enumerate(zip(plan['phases'], receipt['phases'])):
            require(all(actual[k] == phase[k] for k in ('name','kind','command')), 'phase identity differs')
            require(actual['status'] == 'completed' and actual['exit_code'] == 0 and actual['sources_unchanged'],
                    'failed phase')
            require(actual['input_bindings_before'] == actual['input_bindings_after'], 'phase input changed')
            for item in actual['input_bindings_after']:
                bind(item)
            own = Path(plan['output_directory']) / f'{index:02d}-{phase["name"]}-receipt.json'
            require(document(own) == actual, 'standalone phase differs')
            if phase['kind'] == 'model_forward':
                case = next(c for c in protocol['cases'] if c['ids'] == phase['ids'])
                ids = [int(x) for x in Path(case['ids']['path']).read_text().split()]
                require(len(ids) == 447 and ids[-3:] == [4913,3903,819], 'fixed IDs differ')
                path = phase['outputs'][0]
                require(path not in dumps, 'duplicate dump')
                dumps[path] = read_dump(path, ids)
            elif phase['kind'] == 'metric_comparison':
                first, second = phase['command'][-2:]
                require(first in dumps and second in dumps, 'comparison lacks audited dumps')
                saved = [json.loads(line) for line in Path(phase['stdout']).read_text().splitlines()]
                require(len(saved) == 2, 'metric rows differ')
                for row, position in enumerate((444,447)):
                    require(saved[row]['prefix_tokens'] == position and saved[row]['vocabulary'] == 151936
                            and saved[row]['decision_ids'] == [66582,788], 'metric boundaries differ')
                    recalculated = metrics(dumps[first][row], dumps[second][row])
                    compare_saved(saved[row], recalculated, run['name'] == 'q8')
                    comparisons.append(dict(run=run['name'], name=phase['name'], prefix_tokens=position,
                        kind='original-q8' if run['name'] == 'q8' else phase['comparison_kind'],
                        metrics=record(phase['stdout']), max_abs=recalculated['max_abs'],
                        relative_l2=recalculated['relative_l2'], argmax_agree=recalculated['argmax_agree'],
                        first_argmax=recalculated['first_argmax'], second_argmax=recalculated['second_argmax'],
                        first_decision_margin=recalculated['first_concern_minus_clean'],
                        second_decision_margin=recalculated['second_concern_minus_clean'],
                        decision_sign_agree=sign(recalculated['first_concern_minus_clean']) == sign(recalculated['second_concern_minus_clean']),
                        different_float32_values=recalculated['different_float32_values']))
        run_checks.append(dict(name=run['name'], plan=record(run['plan']), receipt=record(run['receipt']),
                               phases=len(plan['phases']), sources_unchanged=True))
    require(len(dumps) == 8 and len(comparisons) == 12, 'full evidence coverage differs')
    f32plan, f32receipt = document(runs[1]['plan']), document(runs[1]['receipt'])
    validation = document(f32plan['validation_receipt'])
    require(validation['status'] == 'completed' and validation['native_exit_code'] == 0 and
            all(validation[k] is True for k in ('every_tensor_exact','all_finite','semantic_metadata_exact')),
            'tensor proof incomplete')
    require(validation['converted'] == f32receipt['converted_model'] and validation['base'] == protocol['model'],
            'tensor proof model differs')
    require(validation['metadata_keys_checked'] == 26 and validation['expected_byte_extent'] == 2526617472 and
            validation['metadata_changes'] == [dict(key='general.file_type', original_hex='0400000007000000', converted_hex='0400000000000000')],
            'metadata proof differs')
    for key, value in f32plan['validation_bindings'].items():
        require(validation[key] == value, 'tensor validator provenance differs')
        bind(value)
    rows = [json.loads(x) for x in Path(f32plan['native_validation_rows']).read_text().splitlines()]
    require(len(rows) == len(validation['tensors']) == 291, 'tensor row coverage differs')
    parser_path = Path(f32plan['validation_bindings']['parser']['path'])
    spec = importlib.util.spec_from_file_location('audited_byte_parser', parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    with Path(protocol['model']['path']).open('rb') as source, Path(validation['converted']['path']).open('rb') as target:
        with mmap.mmap(source.fileno(),0,access=mmap.ACCESS_READ) as original, mmap.mmap(target.fileno(),0,access=mmap.ACCESS_READ) as converted:
            oi, ci = parser.parse_gguf(original), parser.parse_gguf(converted)
            require(oi['metadata_count'] == ci['metadata_count'] == 26 and len(ci['tensors']) == 291, 'model directory differs')
            om, cm = typed_metadata(original), typed_metadata(converted)
            require(set(om) == set(cm) and len(om) == 26, 'typed metadata keys differ')
            require(om['general.file_type'] == struct.pack('<II',4,7) and
                    cm['general.file_type'] == struct.pack('<II',4,0), 'file_type rewrite differs')
            require(all(om[key] == cm[key] for key in om if key != 'general.file_type'),
                    'semantic/tokenizer metadata bytes changed')
            actual_by_name = {t['name']:(i,t) for i,t in enumerate(ci['tensors'])}
            proof_by_name = {t['name']:t for t in validation['tensors']}
            require(len(actual_by_name) == len(proof_by_name) == 291, 'duplicate tensor names')
            total = 0
            for i, (tensor, row) in enumerate(zip(oi['tensors'], rows)):
                j, actual = actual_by_name[tensor['name']]
                proof = proof_by_name[tensor['name']]
                elements = math.prod(tensor['shape'])
                require(row['tensor_index'] == i and row['name'] == tensor['name'] and row['elements'] == elements
                        and row['original_dtype'] == tensor['type'] and row['converted_dtype'] == 0
                        and row['converted_tensor_index'] == j and row['exact_float32_bytes'] is True
                        and row['all_finite'] is True, 'native row proof differs')
                require(actual['shape'] == tensor['shape'] == proof['shape'] and actual['type'] == 0
                        and actual['bytes'] == proof['bytes'] == elements*4, 'converted payload structure differs')
                require(parser.digest(converted, ci['data_offset']+actual['offset'], actual['bytes']) == proof['sha256'],
                        'converted tensor hash differs')
                total += elements
            require(total == 630167424, 'element count differs')
    groups = {}
    for kind in ('original-q8','native-packing','aligned-engine'):
        captures = [c for c in comparisons if c['kind'] == kind]
        require(len(captures) == 4, 'group coverage differs')
        groups[kind] = dict(captures=4, full_vocabulary_pairs=4*151936,
            max_abs=max(c['max_abs'] for c in captures), max_relative_l2=max(c['relative_l2'] for c in captures),
            all_argmax_agree=all(c['argmax_agree'] for c in captures),
            all_decision_signs_agree=all(c['decision_sign_agree'] for c in captures),
            all_values_bit_identical=all(c['different_float32_values'] == 0 for c in captures))
    summary = document(ALIGNMENT/'summary.json')
    require(summary['receipt'] == record(runs[1]['receipt']), 'summary covers different run')
    for kind in ('native-packing','aligned-engine'):
        saved = summary['aggregates'][kind]
        actual = groups[kind]
        require(saved['all_argmax_agree'] == actual['all_argmax_agree'] and
                saved['all_decision_margin_signs_agree'] == actual['all_decision_signs_agree'], 'summary signs differ')
        require(math.isclose(saved['maximum_absolute_difference'], actual['max_abs'], rel_tol=5e-12, abs_tol=1e-14)
                and math.isclose(saved['maximum_relative_l2'], actual['max_relative_l2'], rel_tol=5e-12, abs_tol=1e-14),
                'summary numerical aggregate differs')
    output = dict(status='pass', audit_source=record(__file__), runs=run_checks,
        summary=record(ALIGNMENT/'summary.json'), unique_current_bindings_verified=len(CACHE),
        raw_dumps=[record(path) for path in sorted(dumps)], dump_count=8, capture_vectors=16,
        finite_saved_logits_checked=16*151936, complete_comparison_vectors=12,
        independent_scalar_recalculation='Every saved scalar, changed-float count, argmax, top10 and decision margin recomputed from full raw vectors; stable lowest-ID ties. Tiny comparison tolerance covers C sequential-double versus Python fsum accumulation only, not model correctness.',
        aggregates=groups, captures=comparisons,
        tensor_proof=dict(receipt=record(f32plan['validation_receipt']), native_rows=record(f32plan['native_validation_rows']),
            original_model=protocol['model'], converted_model=validation['converted'], tensors=291,
            stored_values=630167424, all_converted_payload_hashes_rechecked=True,
            all_26_typed_metadata_values_independently_rechecked=True,
            native_every_value_proof='Audited independent native verifier completed exit0 and each291 row/shape/dtype/index/exact-finite flag matches both bound GGUF directories; proof covers all630167424 values. No second dequantization was run by auditor.'),
        interpretation=dict(scope='Only two fixed original-base prompts at assistant header and common3-token prefix; no v5 weights/generation/selection or general runtime proof.',
            finding='Compare original Q8, native packed-vs-F32, and aligned F32 results separately. Agreement in these captures constrains a broad forward-corruption explanation here; it does not establish all-model/all-context/training correctness.',
            unchanged_selection=True),
        model_forwards_by_auditor=0, model_conversions_by_auditor=0, builds_by_auditor=0)
    target = AUDIT/'external-forward-results-independent-audit.json'
    with target.open('x') as stream:
        stream.write(json.dumps(output,indent=2)+'\n')
    print(json.dumps(dict(status='pass', audit=record(target), aggregates=groups),indent=2))

if __name__ == '__main__':
    main()
