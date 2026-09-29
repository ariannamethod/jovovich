#!/usr/bin/env python3
"""Independent read-only byte audit of the two selected convergence exports."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import math
import mmap
from pathlib import Path
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def align32(n):
    return (n + 31) & ~31


def parse_gguf(data):
    pos = 0

    def take(n):
        nonlocal pos
        require(0 <= n <= len(data) - pos, 'truncated GGUF header')
        value = data[pos:pos+n]
        pos += n
        return value

    def integer(fmt):
        return struct.unpack('<' + fmt, take(struct.calcsize('<' + fmt)))[0]

    def string():
        return take(integer('Q'))

    def skip_value(kind):
        sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4,
                 7: 1, 10: 8, 11: 8, 12: 8}
        if kind in sizes:
            take(sizes[kind])
        elif kind == 8:
            string()
        elif kind == 9:
            element, count = integer('I'), integer('Q')
            require(element != 9, 'nested metadata array is unsupported')
            for _ in range(count):
                skip_value(element)
        else:
            raise ValueError(f'unsupported metadata type {kind}')

    require(take(4) == b'GGUF', 'not a GGUF')
    version, count, kv_count = integer('I'), integer('Q'), integer('Q')
    require(version == 3, 'expected GGUF v3')
    for _ in range(kv_count):
        string()
        skip_value(integer('I'))
    kv_end = pos
    tensors = []
    for _ in range(count):
        name, ndim = string().decode('utf-8'), integer('I')
        require(1 <= ndim <= 4, f'invalid dimensions: {name}')
        shape = [integer('Q') for _ in range(ndim)]
        require(all(shape), f'zero dimension: {name}')
        mutable_at = pos
        kind, offset = integer('I'), integer('Q')
        # The audited base contains F32 and Q8_0; F16 is also explicit.
        sizes = {0: (1, 4), 1: (1, 2), 8: (32, 34)}
        require(kind in sizes, f'unsupported tensor type {kind}: {name}')
        block, width = sizes[kind]
        elements = math.prod(shape)
        require(elements % block == 0, f'partial quantization block: {name}')
        size = elements // block * width
        tensors.append(dict(name=name, shape=shape, type=kind, offset=offset,
                            bytes=size, mutable_at=mutable_at))
    data_offset = align32(pos)
    require(data_offset <= len(data), 'truncated tensor directory')
    require(len({t['name'] for t in tensors}) == count, 'duplicate tensor name')
    for tensor in tensors:
        end = data_offset + tensor['offset'] + tensor['bytes']
        require(tensor['offset'] % 32 == 0 and end <= len(data),
                f'tensor outside aligned file extent: {tensor["name"]}')
    return dict(version=version, metadata_count=kv_count, kv_end=kv_end,
                data_offset=data_offset, tensors=tensors)


def digest(data, start=0, length=None):
    length = len(data) - start if length is None else length
    h = hashlib.sha256()
    for offset in range(start, start + length, 1024 * 1024):
        h.update(data[offset:min(offset + 1024 * 1024, start + length)])
    return h.hexdigest()


def equal_payload(a, start_a, b, start_b, length):
    for offset in range(0, length, 1024 * 1024):
        n = min(1024 * 1024, length - offset)
        if a[start_a+offset:start_a+offset+n] != b[start_b+offset:start_b+offset+n]:
            return False
    return True


def normalized_header(data, info):
    header = bytearray(data[:info['data_offset']])
    for tensor in info['tensors']:
        p = tensor['mutable_at']
        header[p:p+12] = bytes(12)  # Only dtype and offset may change.
    return header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    selection_path = root / 'models/convergence-selected-models.json'
    selection_raw = selection_path.read_bytes()
    selection = json.loads(selection_raw)
    require(selection['examples']['bytes'] == 714116992 and
            not selection['examples']['sha256'].startswith('092af4c0'),
            'recovery has not refreshed the selected-model receipt yet')
    receipt = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                   script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   selection_sha256=hashlib.sha256(selection_raw).hexdigest(),
                   verification='independent standard-library GGUF parser and direct byte comparisons',
                   models={})
    with ExitStack() as stack:
        def mapped(path):
            stream = stack.enter_context(path.open('rb'))
            return stack.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ))
        base = mapped(root / 'models/base-qwen.gguf')
        base_info = parse_gguf(base)
        base_sha = digest(base)
        require(base_sha == json.loads((root / 'model.json').read_text())['sha256'],
                'base model does not match model.json')
        receipt['base'] = dict(path='models/base-qwen.gguf', bytes=len(base), sha256=base_sha,
                              tensor_count=len(base_info['tensors']))
        adapted = {f'blk.23.ffn_{part}.weight': part for part in ('gate', 'up', 'down')}
        for objective in ('tokens', 'examples'):
            selected = selection[objective]
            require(selected['epoch'] == 12, 'expected selected epoch 12')
            model = mapped(root / selected['path'])
            info = parse_gguf(model)
            require(len(model) == selected['bytes'] == 714116992, 'unexpected export size')
            model_sha = digest(model)
            require(model_sha == selected['sha256'], 'model hash differs from selected receipt')
            require(model[:info['kv_end']] == base[:base_info['kv_end']], 'header/metadata changed')
            require(normalized_header(model, info) == normalized_header(base, base_info),
                    'header changed outside tensor dtype/offset fields')
            require(len(info['tensors']) == len(base_info['tensors']) == 291, 'tensor count changed')
            cursor, unchanged, replaced, payloads = 0, 0, 0, []
            for original, actual in zip(base_info['tensors'], info['tensors']):
                name = actual['name']
                require((name, actual['shape']) == (original['name'], original['shape']),
                        f'tensor identity changed: {name}')
                require(actual['offset'] == cursor, f'noncontiguous tensor layout: {name}')
                cursor = align32(cursor + actual['bytes'])
                start = info['data_offset'] + actual['offset']
                if name in adapted:
                    reference_path = f'models/convergence-{objective}.epoch12.{adapted[name]}.f32'
                    expected = mapped(root / reference_path)
                    expected_start = 0
                    require(actual['type'] == 0 and len(expected) == actual['bytes'],
                            f'adapted tensor is not exact-sized F32: {name}')
                    replaced += 1
                else:
                    reference_path = 'models/base-qwen.gguf'
                    expected, expected_start = base, base_info['data_offset'] + original['offset']
                    require(actual['type'] == original['type'] and actual['bytes'] == original['bytes'],
                            f'non-adapted tensor type/size changed: {name}')
                    unchanged += 1
                require(equal_payload(model, start, expected, expected_start, actual['bytes']),
                        f'tensor payload mismatch: {name}')
                payloads.append(dict(name=name, type=actual['type'], bytes=actual['bytes'],
                                     sha256=digest(model, start, actual['bytes']),
                                     reference=reference_path, exact_bytes_equal=True))
            expected_extent = info['data_offset'] + cursor
            require(expected_extent == len(model), 'trailing or missing model payload bytes')
            require(unchanged == 288 and replaced == 3, 'unexpected replacement count')
            receipt['models'][objective] = dict(path=selected['path'], epoch=12, bytes=len(model),
                sha256=model_sha, tensor_count=len(payloads), expected_extent=expected_extent,
                data_offset=info['data_offset'], header_metadata_equal=True,
                header_equal_except_tensor_types_offsets=True, non_adapted_equal=unchanged,
                adapted_equal_epoch12_f32=replaced, valid=True, tensors=payloads)
    require(selection_path.read_bytes() == selection_raw, 'selected receipt changed during audit')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as out:
        json.dump(receipt, out, indent=2)
        out.write('\n')
    print(json.dumps({k: {p: v[p] for p in ('bytes', 'sha256', 'non_adapted_equal',
                                           'adapted_equal_epoch12_f32', 'valid')}
                      for k, v in receipt['models'].items()}))


if __name__ == '__main__':
    main()
