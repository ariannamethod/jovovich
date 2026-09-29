"""Archive only the collected manifest's source/evidence allowlists; default is local validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile


REPO = 'ataeff/jovovich'
RESULTS = 'training/results/2026-09-29-small-step'
PREFIX = 'experiments/decision-small-step/'
HEADING = '## Decision-only small-step control (2026-09-29)'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(directory, name, expected=None):
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'manifest has a noncanonical relative path')
    local = directory / name
    require(local.resolve().is_relative_to(directory.resolve()) and local.is_file(),
            f'manifest file is missing or escapes its directory: {name}')
    data = local.read_bytes()
    if expected is not None:
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
                f'invalid manifest hash: {name}')
        require(sha(data) == expected, f'manifest hash mismatch: {name}')
    return data


def collect(root):
    directory = root / RESULTS
    manifest_data = checked_file(directory, 'manifest.json')
    manifest = json.loads(manifest_data)
    files = {}
    for key, base, remote in [('source_sha256', root, PREFIX + 'source/'),
                              ('evidence_sha256', directory, PREFIX + 'evidence/')]:
        hashes = manifest.get(key)
        require(isinstance(hashes, dict) and hashes, f'missing manifest allowlist: {key}')
        for name, digest in hashes.items():
            require(not name.endswith(('.gguf', '.lora', '.f32')), 'weights are a separate archive')
            require(remote + name not in files, 'duplicate archive path')
            files[remote + name] = checked_file(base, name, digest)
    require(PREFIX + 'evidence/manifest.json' not in files, 'manifest must not hash itself')
    files[PREFIX + 'evidence/manifest.json'] = manifest_data
    # The frozen comparison and following corpus repair must both be recoverable.
    for name in ('training/train_mlp.c', 'src/infer.c', 'training/sft_review_v2.jsonl',
                 'training/sft_review_v3.jsonl', 'training/review_holdout_v2.jsonl'):
        require(PREFIX + 'source/' + name in files, f'required source omitted: {name}')
    require(manifest['training']['learning_rate'] == 0.0001 and
            manifest['training']['objective'] == 'decisions' and
            manifest['runtime_model_promoted'] is False, 'unexpected experiment manifest')
    scores = json.loads(files[PREFIX + 'evidence/scores.json'])
    selected = scores['selected']
    require(scores['selected_update'] == manifest['selected_model']['update'] == 100,
            'selection disagrees with this completed control')
    require(selected['correct_targets'] == 26 and selected['complete_decision_pairs'] == 6,
            'selected diagnostic totals disagree with this completed control')
    section = (
        f'\n\n{HEADING}\n\n'
        'The matched decision-only control reduced the learning rate from 0.001 to 0.0001, '
        'using the same v2 corpus, frozen native trainer, fresh initialization and 100 updates. '
        f'The unchanged selector chose update 100: {selected["correct_targets"]}/40 '
        f'teacher-forced decision targets and {selected["complete_decision_pairs"]}/20 complete '
        f'pairs, with decision CE {selected["mean_decision_ce"]:.8f}. '
        'Generated-review outcomes and token diagnostics are reported separately.\n\n'
        'Raw natural generations, the two-model shared-prefix diagnostic, assessments and '
        'reproduction scripts are preserved under '
        '`experiments/decision-small-step/evidence/`; the manifest-listed source snapshot '
        'is under `experiments/decision-small-step/source/`. The v3 corpus wording repairs '
        'are archived for subsequent work; this experiment trained on v2. '
        'The production model lock remains the base checkpoint.\n'
    )
    return manifest, files, section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-parent', required=True, help='exact current private HF commit')
    parser.add_argument('--upload', action='store_true', help='commit and verify; otherwise validate locally only')
    parser.add_argument('--token-file', type=Path, default=Path('../recovered/4astra.txt'),
                        help='used only for upload when HF_TOKEN is unset')
    parser.add_argument('--receipt', type=Path, default=Path('models/decision-small-step-hf-evidence.json'))
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.expected_parent), 'expected-parent must be a full commit SHA')
    root = Path.cwd().resolve()
    manifest, files, section = collect(root)
    if not args.upload:
        print(json.dumps(dict(phase='local_validation_only', repo=REPO, files=len(files),
                             manifest_sha256=sha(files[PREFIX + 'evidence/manifest.json']),
                             expected_parent=args.expected_parent)))
        return
    require(not args.receipt.exists(), 'archive receipt already exists; inspect it before retrying')
    tracked_receipt = root / RESULTS / 'hf-evidence.json'
    require(not tracked_receipt.exists(), 'tracked archive receipt already exists')
    require('hf-evidence.json' not in manifest['evidence_sha256'],
            'the post-upload receipt must stay outside the frozen evidence manifest')
    token = os.environ.get('HF_TOKEN')
    if not token:
        match = re.search(r'hf_[A-Za-z0-9]+', args.token_file.read_text())
        require(match is not None, 'token file has no HF token')
        token = match.group()
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
    api = HfApi(token=token)
    info = api.model_info(REPO)
    require(info.private, 'archive repository must remain private')
    require(info.sha == args.expected_parent, 'HF head moved; expected-parent guard refused the upload')
    remote_names = {entry.rfilename for entry in info.siblings}
    require(not any(name.startswith((PREFIX + 'source/', PREFIX + 'evidence/')) for name in remote_names),
            'this source/evidence archive already exists; refuse overwrite')
    with tempfile.TemporaryDirectory(prefix='jovovich-small-step-archive-') as cache:
        card_path = hf_hub_download(REPO, 'README.md', revision=args.expected_parent,
                                    token=token, cache_dir=cache, force_download=True)
        card = Path(card_path).read_bytes()
        require(HEADING not in card.decode('utf-8'), 'the model card already has this experiment section')
        files['README.md'] = card + section.encode('utf-8')
        expected = {name: dict(bytes=len(data), sha256=sha(data)) for name, data in files.items()}
        print(json.dumps(dict(phase='uploading', files=len(files), parent=args.expected_parent)), flush=True)
        commit = api.create_commit(REPO,
            operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=data)
                        for name, data in files.items()],
            commit_message='Archive smaller-step decision evidence, source snapshot and factual model-card update',
            parent_commit=args.expected_parent)
        final = api.model_info(REPO, revision=commit.oid)
        require(final.private, 'archive privacy changed')
        verified = []
        for name, metadata in expected.items():
            downloaded = hf_hub_download(REPO, name, revision=commit.oid, token=token,
                                         cache_dir=cache, force_download=True)
            data = Path(downloaded).read_bytes()
            require(len(data) == metadata['bytes'] and sha(data) == metadata['sha256'],
                    f'uploaded file verification failed: {name}')
            verified.append(dict(file=name, **metadata))
        record = dict(repo=REPO, private=True, parent_commit=args.expected_parent,
                      commit=commit.oid, files_uploaded=len(files), verified_by_download=verified,
                      manifest_sha256=sha(files[PREFIX + 'evidence/manifest.json']),
                      prior_card_sha256=sha(card), card_heading=HEADING,
                      source_parent_commit=manifest['parent_commit'],
                      receipt_manifest_exclusion='Created after upload; excluded from the frozen manifest to avoid self-reference.')
        with args.receipt.open('x') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
        with tracked_receipt.open('x') as output:
            json.dump(record, output, indent=2)
            output.write('\n')
        print(json.dumps(dict(phase='complete', commit=commit.oid, private=True,
                             verified_files=len(verified), receipt=str(args.receipt),
                             tracked_receipt=str(tracked_receipt.relative_to(root)))), flush=True)


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        # HTTP exceptions can include signed URLs; never print them or credentials.
        raise SystemExit(f'archive failed ({type(error).__name__}); inspect state before retrying') from None
