"""Validate the completed joint-control weights locally; --upload commits and verifies them."""
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys


REPO = 'ataeff/jovovich'
STEM = 'models/joint-review'
PREFIX = 'experiments/joint-review/'
UPDATES = (25, 50, 75, 100)
PROJECTIONS = ('gate', 'up', 'down')


class ArchiveValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ArchiveValidationError(message)


def read_json(path):
    require(Path(path).is_file(), f'required completed-run file is missing: {path}')
    return json.loads(Path(path).read_text())


def read_jsonl(path):
    require(Path(path).is_file(), f'required completed-run file is missing: {path}')
    text = Path(path).read_text()
    require(text.endswith('\n'), f'incomplete JSONL: {path}')
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class FileHashes:
    """Stream each unchanged file once per invocation, including large GGUF files."""
    def __init__(self):
        self.cache = {}

    def describe(self, path):
        path = Path(path)
        require(path.is_file(), f'archive input is missing: {path}')
        before = path.stat()
        key = (before.st_dev, before.st_ino, before.st_size,
               before.st_mtime_ns, before.st_ctime_ns)
        if key not in self.cache:
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    digest.update(chunk)
            after = path.stat()
            require(key == (after.st_dev, after.st_ino, after.st_size,
                            after.st_mtime_ns, after.st_ctime_ns),
                    f'file changed during hashing: {path}')
            self.cache[key] = dict(bytes=before.st_size, sha256=digest.hexdigest())
        return dict(self.cache[key])

    def verify(self, path, digest):
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest),
                f'invalid expected SHA256: {path}')
        actual = self.describe(path)
        require(actual['sha256'] == digest, f'archive input hash changed: {path}')
        return actual


def adapter_shape(path, target, rank, alpha):
    data = Path(path).read_bytes()
    require(len(data) >= 33, f'truncated LoRA header: {path}')
    magic, version, targets = struct.unpack_from('<III', data)
    require(magic == 0x4c4f5241 and version == 1 and targets == 1,
            f'unexpected native LoRA format: {path}')
    name_length = data[12]
    start = 13 + name_length
    require(len(data) >= start + 20 and data[13:start].decode('utf-8') == target,
            f'LoRA target mismatch: {path}')
    layers, actual_rank, actual_alpha, inputs, outputs = struct.unpack_from('<IIfII', data, start)
    require(layers == 1 and actual_rank == rank and actual_alpha == alpha and inputs > 0 and outputs > 0,
            f'LoRA dimensions or scaling mismatch: {path}')
    parameters = rank * (inputs + outputs)
    require(len(data) == start + 20 + parameters * 4, f'LoRA payload size mismatch: {path}')
    require(all(math.isfinite(value) for (value,) in struct.iter_unpack('<f', data[start + 20:])),
            f'nonfinite LoRA parameter: {path}')
    return inputs, outputs, parameters


def collect(hashes):
    # Completion gates run before credential loading or any remote operation.
    resource = read_json(STEM + '-resource.json')
    require(resource.get('exit_code') == 0 and resource.get('sources_unchanged') is True and
            resource.get('objective') == 'joint', 'joint training did not finish successfully')
    plan = read_json(STEM + '-plan.json')
    source = read_json(STEM + '-training-source.json')
    hashes.verify(STEM + '-plan.json', source['plan_sha256'])
    fixed = plan['fixed_training']
    require(plan['checkpoint_selection']['saved_updates'] == list(UPDATES) and
            plan['checkpoint_selection']['eligible_updates'] == [25, 50, 100] and
            fixed['optimizer_updates'] == 100, 'unexpected frozen checkpoint schedule')
    expected_command = ['build/jovovich-train-mlp', 'models/base-qwen.gguf', STEM + '.bin',
                        STEM, '100', '0.0001', '40', '25', 'joint', STEM + '.pairs']
    require(resource['command'] == expected_command, 'training command changed from this control')
    for name, item in plan['frozen_training'].items():
        require(source[name + '_sha256'] == item['sha256'], f'training receipt disagrees: {name}')
        hashes.verify(item['path'], item['sha256'])
    for item in plan['frozen_evaluation'].values():
        hashes.verify(item['path'], item['sha256'])
    hashes.verify(plan['training_runner']['path'], plan['training_runner']['sha256'])
    hashes.verify(fixed['dataset'], fixed['dataset_sha256'])
    hashes.verify(STEM + '.pairs', fixed['pair_map_sha256'])
    base = hashes.verify('models/base-qwen.gguf', fixed['base_sha256'])
    pin = subprocess.run(['git', '-C', 'deps/notorch', 'rev-parse', 'HEAD'], check=True,
                         capture_output=True, text=True).stdout.strip()
    require(pin == fixed['notorch_pin'], 'native substrate pin changed')

    # Reuse the strict, frozen scorer to cover all 101 readouts and the selector.
    sys.path.insert(0, str(Path('training').resolve()))
    from score_decisions import score_run
    metrics = read_jsonl(STEM + '-metrics.jsonl')
    scored = score_run(read_jsonl(fixed['dataset']), metrics)
    scores = read_json(STEM + '-scores.json')
    require(scored['objective'] == 'joint' and
            all(scores.get(key) == value for key, value in scored.items()),
            'stored scores disagree with the completed run')
    hashes.verify(STEM + '-metrics.jsonl', scores['metrics_sha256'])
    hashes.verify(fixed['dataset'], scores['sft_sha256'])
    selected = read_json(STEM + '-selected-model.json')
    require(selected.get('update') == scores['selected_update'] and selected['update'] in (25, 50, 100),
            'selected checkpoint disagrees with the frozen selector')
    require(selected.get('path') == STEM + '-selected.gguf', 'unexpected selected-model path')
    model = hashes.verify(selected['path'], selected['sha256'])
    require(model['bytes'] == selected['bytes'], 'selected-model byte count disagrees')
    audit = read_json(STEM + '-export-audit.json')
    require(audit.get('valid') is True and audit.get('metadata_equal') is True and
            audit.get('adapted') == 3 and audit.get('unchanged') == 288 and
            audit.get('prefix') == f'{STEM}.epoch{selected["update"]:02d}' and
            audit.get('expected_extent') == model['bytes'] and
            {k: audit['model'][k] for k in ('bytes', 'sha256')} == model and
            {k: audit['base'][k] for k in ('bytes', 'sha256')} == base,
            'selected GGUF export audit disagrees')
    parity = read_jsonl(STEM + '-parity.jsonl')
    require([r.get('row') for r in parity] == [0, 1, 2] and
            all(r.get('pass') is True and r['argmax_agree'] == r['completion_tokens'] for r in parity),
            'selected GGUF parity checks are incomplete')
    checked = read_json(STEM + '-joint-evaluation-model-check.json')
    require(checked.get('unchanged') is True and checked.get('sha256') == model['sha256'],
            'completed evaluation model receipt disagrees')

    files = {}
    shapes = {}
    initial = metrics[0]
    for update in UPDATES:
        parameters = 0
        for projection in PROJECTIONS:
            local = Path(f'{STEM}.epoch{update:02d}.{projection}.lora')
            require(local.is_file(), f'checkpoint adapter is missing: {local}')
            shape = adapter_shape(local, f'blk.{initial["layer"]}.ffn_{projection}.weight',
                                  fixed['rank'], fixed['alpha'])
            if projection in shapes:
                require(shape == shapes[projection], f'adapter dimensions changed: {local}')
            shapes[projection] = shape
            parameters += shape[2]
            files[PREFIX + local.name] = local
        require(parameters == fixed['trainable_parameters'], 'adapter parameter count disagrees')
    require(shapes['gate'] == shapes['up'] and shapes['down'][:2] == shapes['gate'][:2][::-1],
            'MLP adapter projection dimensions disagree')
    files[PREFIX + Path(selected['path']).name] = Path(selected['path'])
    files[PREFIX + 'sft_review_v2.jsonl'] = Path(fixed['dataset'])
    files[PREFIX + 'joint-review.bin'] = Path(STEM + '.bin')
    files[PREFIX + 'joint-review.pairs'] = Path(STEM + '.pairs')
    require(len(files) == 16, 'archive allowlist must contain 13 weights and three dataset files')
    expected = {name: hashes.describe(local) for name, local in files.items()}
    provenance = dict(selected_update=selected['update'], selected_model=model,
                      base_model=base, plan_sha256=source['plan_sha256'],
                      training_source_sha256=source['source_sha256'],
                      training_binary_sha256=source['binary_sha256'],
                      dataset_sha256=fixed['dataset_sha256'],
                      dataset_binary_sha256=source['dataset_binary_sha256'],
                      pair_map_sha256=source['pair_map_sha256'],
                      metrics_sha256=scores['metrics_sha256'], notorch_pin=pin,
                      source_parent_commit=plan['parent_commit'])
    return files, expected, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-parent', required=True, help='exact current private HF commit')
    parser.add_argument('--upload', action='store_true', help='commit and verify; default validates locally')
    parser.add_argument('--token-file', type=Path, default=Path('../recovered/4astra.txt'))
    parser.add_argument('--receipt', type=Path, default=Path(STEM + '-hf-weights.json'))
    parser.add_argument('--cache-dir', type=Path, default=Path('/tmp/jovovich-hf-joint-archive'))
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.expected_parent), 'expected-parent must be a full commit SHA')
    hashes = FileHashes()
    files, expected, provenance = collect(hashes)
    if not args.upload:
        print(json.dumps(dict(phase='local_validation_only', repo=REPO, files=len(files),
                             weights=13, expected_parent=args.expected_parent, **provenance)))
        return
    require(not args.receipt.exists(), 'archive receipt exists; inspect it before retrying')
    token = os.environ.get('HF_TOKEN')
    if not token:
        match = re.search(r'hf_[A-Za-z0-9]+', args.token_file.read_text())
        require(match is not None, 'token file has no HF token')
        token = match.group()
    logging.getLogger('huggingface_hub').setLevel(logging.CRITICAL)
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
    api = HfApi(token=token)
    info = api.model_info(REPO)
    require(info.private is True, 'archive repository must remain private')
    require(info.sha == args.expected_parent, 'HF head moved; expected-parent guard refused upload')
    require(not any(item.rfilename.startswith(PREFIX) for item in info.siblings),
            'joint-review archive prefix already exists; refuse overwrite')
    # Recheck file identity/content after the remote guard, before the single commit.
    require(all(hashes.describe(local) == expected[name] for name, local in files.items()),
            'archive input changed before upload')
    print(json.dumps(dict(phase='uploading', files=len(files), parent=args.expected_parent)), flush=True)
    commit = api.create_commit(REPO,
        operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(local))
                    for name, local in files.items()],
        commit_message='Archive joint decision and complete-review checkpoints with frozen v2 inputs',
        parent_commit=args.expected_parent)
    commit_id = commit.oid
    require(re.fullmatch('[0-9a-f]{40}', commit_id), 'upload returned an invalid commit ID')
    # Record the committed ID immediately so verification can be recovered after interruption.
    print(json.dumps(dict(phase='committed', commit=commit_id, files=len(files))), flush=True)
    final = api.model_info(REPO, revision=commit_id)
    require(final.private is True and final.sha == commit_id, 'pinned archive state changed')
    verified = []
    for name, metadata in expected.items():
        downloaded = hf_hub_download(REPO, name, revision=commit_id, token=token,
                                     cache_dir=args.cache_dir)
        require(hashes.describe(downloaded) == metadata, f'pinned download verification failed: {name}')
        verified.append(dict(file=name, **metadata))
    require(all(hashes.describe(local) == expected[name] for name, local in files.items()),
            'local weights changed during upload')
    record = dict(repo=REPO, private=True, commit=commit_id, parent_commit=args.expected_parent,
                  files_uploaded=len(files), verified_weights=[v for v in verified if v['file'].endswith(('.lora', '.gguf'))],
                  verified_by_download=verified, **provenance)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open('x') as output:
        json.dump(record, output, indent=2)
        output.write('\n')
    print(json.dumps(dict(phase='complete', commit=commit_id, private=True,
                         verified_files=len(verified), verified_weights=13, receipt=str(args.receipt))), flush=True)


if __name__ == '__main__':
    try:
        main()
    except ArchiveValidationError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        # Remote exceptions can contain signed URLs; keep credentials and URLs out of output.
        raise SystemExit(f'archive failed ({type(error).__name__}); inspect the recorded phase before retrying') from None
