"""Validate a frozen counterbalanced archive; --upload commits its allowlists privately."""
import argparse
import concurrent.futures
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
import re
import tempfile

from archive_counterbalanced_weights import ARMS, COHORTS, CONTROL_SHA256, read_token, require


REPO = 'ataeff/jovovich'
RESULTS = 'training/results/2026-10-01-counterbalanced-review'
PREFIX = 'experiments/counterbalanced-review/'
HEADING = '## Counterbalanced review corpus (2026-10-01)'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(directory, name, expected=None):
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'manifest path must be a canonical relative path')
    local = directory / name
    require(local.resolve().is_relative_to(directory.resolve()) and local.is_file(),
            f'missing or external manifest file: {name}')
    data = local.read_bytes()
    require(not re.search(rb'hf_[A-Za-z0-9]{20,}', data), f'credential-like content in archive input: {name}')
    require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data),
            f'private-key-like content in archive input: {name}')
    if expected is not None:
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), f'invalid hash: {name}')
        require(sha(data) == expected, f'manifest hash mismatch: {name}')
    return data


def collect(root):
    directory = root / RESULTS
    manifest_bytes = checked_file(directory, 'manifest.json')
    manifest = json.loads(manifest_bytes)
    files = {}
    for key, base, remote in [('source_sha256', root, PREFIX + 'source/'),
                              ('evidence_sha256', directory, PREFIX + 'evidence/')]:
        hashes = manifest.get(key)
        require(isinstance(hashes, dict) and hashes, f'missing allowlist: {key}')
        for name, digest in hashes.items():
            require(not name.endswith(('.gguf', '.lora', '.f32', '.bin', '.pairs')),
                    'weights and binary datasets use their separate archive')
            require(remote + name not in files, 'duplicate archive path')
            files[remote + name] = checked_file(base, name, digest)
    require(PREFIX + 'evidence/manifest.json' not in files, 'manifest must not hash itself')
    files[PREFIX + 'evidence/manifest.json'] = manifest_bytes
    for name in ('training/train_mlp.c', 'src/infer.c', 'training/sft_review_v4.jsonl',
                 'training/build_review_v4.mjs', 'training/score_decisions.py', 'training/review_holdout_v2.jsonl'):
        require(PREFIX + 'source/' + name in files, f'required source missing: {name}')
    def evidence(name):
        require(PREFIX + 'evidence/' + name in files, f'required evidence missing: {name}')
        return files[PREFIX + 'evidence/' + name]
    def parsed(name):
        return json.loads(evidence(name))
    require(sha(evidence('infer-experiment.c')) == manifest['experiment_inference']['sha256'],
            'experiment inference snapshot mismatch')
    require(manifest['training']['objective'] == 'joint' and manifest['runtime_model_promoted'] is False and
            manifest['comparator_sha256'] == CONTROL_SHA256, 'unexpected experiment')
    scores, summary, semantics = (parsed(name) for name in ('scores.json', 'generation-summary.json', 'semantic-assessment.json'))
    require(semantics.get('complete') is True and semantics['scope']['total_responses'] == 176,
            'manual semantic assessment is incomplete')
    require(scores['selected_update'] == manifest['selected_model']['update'] and
            scores['selected_update'] in (25, 50, 100), 'checkpoint selection disagrees')
    require(scores['metrics_sha256'] == sha(evidence('metrics.jsonl')) and
            scores['sft_sha256'] == sha(files[PREFIX + 'source/training/sft_review_v4.jsonl']),
            'score provenance mismatch')
    require(set(summary['cohorts']) == set(semantics['cohorts']) == set(ARMS), 'arm coverage disagrees')
    expected_cohorts = {}
    for arm in ARMS:
        model_hash = manifest['selected_model']['sha256'] if arm == 'counterbalanced' else CONTROL_SHA256
        require(set(summary['cohorts'][arm]) == set(semantics['cohorts'][arm]) == set(COHORTS),
                f'cohort coverage disagrees: {arm}')
        for name, expected in COHORTS.items():
            measured = summary['cohorts'][arm][name]
            judged = semantics['cohorts'][arm][name]
            counts, manual = measured['counts'], judged['counts']
            require(measured['model_sha256'] == model_hash and
                    counts['cases'] == len(measured['cases']) == manual['cases'] == len(judged['cases']) == expected and
                    counts['expected_concerns'] == counts['expected_clean'] == counts['pairs'] == expected // 2,
                    f'generation summary count mismatch: {arm}/{name}')
            require(0 <= manual['grounded_concern_reviews'] <= manual['genuine_issues_detected'] <= counts['expected_concerns'] and
                    0 <= manual['correct_clean_reviews'] <= counts['expected_clean'] and
                    0 <= manual['full_review_pairs'] <= counts['pairs'] and
                    manual['full_reviews_pass'] == manual['grounded_concern_reviews'] + manual['correct_clean_reviews'],
                    f'manual semantic counts disagree: {arm}/{name}')
            raw = evidence(f'{arm}-{name}.jsonl')
            require(raw.endswith(b'\n'), f'incomplete cohort JSONL: {arm}/{name}')
            rows = [json.loads(line) for line in raw.splitlines()]
            require(len(rows) == len({row['name'] for row in rows}) == expected and
                    all(row['model_sha256'] == model_hash and row['returncode'] == 0 and row['mode'] == 'natural'
                        for row in rows), f'raw cohort coverage or provenance changed: {arm}/{name}')
            expected_cohorts[f'{arm}-{name}.jsonl'] = expected
            require(manifest['semantic_counts'][arm][name] == manual, 'manifest semantic counts disagree')
    require(summary['protocol']['generated_responses'] == 176 and
            manifest['result_counts']['generated_responses'] == 176 and
            manifest['result_counts']['cohorts'] == expected_cohorts,
            'generation totals disagree')
    receipt = parsed('hf-weights.json')
    require(receipt['private'] is True and receipt['repo'] == REPO and
            re.fullmatch('[0-9a-f]{40}', receipt['commit']) and
            receipt['selected_model']['sha256'] == manifest['selected_model']['sha256'],
            'private weights receipt disagrees')
    for name in ('counterbalanced-manual-judgments.json', 'fresh-transfer.jsonl', 'fresh-transfer-audit.json',
                 'native-preflight.json', 'corpus-audit.json', 'protocol-audit.json',
                 'archive_counterbalanced_weights.py', 'collect_counterbalanced_review.py',
                 'archive_counterbalanced_evidence.py'):
        evidence(name)
    return manifest, files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-head', '--expected-parent', dest='expected_parent', required=True,
                        help='exact current private HF commit')
    parser.add_argument('--upload', action='store_true', help='commit and download-verify; default validates locally')
    parser.add_argument('--token-file', type=Path, default=Path('../recovered/4astra.txt'))
    parser.add_argument('--receipt', type=Path, default=Path('models/counterbalanced-review-hf-evidence.json'))
    parser.add_argument('--card-section', type=Path,
                        help='optional reviewed Markdown section appended byte-for-byte to the pinned existing model card')
    parser.add_argument('--card-heading', default=HEADING, help='unique heading required exactly once in --card-section')
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.expected_parent), 'expected-head must be a full commit SHA')
    root = Path.cwd().resolve()
    manifest, files = collect(root)
    section = None
    if args.card_section is not None:
        section = args.card_section.read_bytes()
        require(not re.search(rb'hf_[A-Za-z0-9]{20,}', section), 'credential-like content in model card section')
        require(section.decode('utf-8').count(args.card_heading) == 1 and
                args.card_heading.startswith('## '), 'model-card section must contain its unique heading once')
        require(section.startswith(b'\n') and section.endswith(b'\n'), 'model-card section must preserve newline boundaries')
    if not args.upload:
        print(json.dumps(dict(phase='local_validation_only', repo=REPO, files=len(files),
                             card_section=section is not None,
                             manifest_sha256=sha(files[PREFIX + 'evidence/manifest.json']),
                             expected_parent=args.expected_parent)))
        return
    tracked_receipt = root / RESULTS / 'hf-evidence.json'
    require(not args.receipt.exists() and not tracked_receipt.exists(), 'archive receipt already exists')
    require('hf-evidence.json' not in manifest['evidence_sha256'], 'receipt must stay outside the frozen manifest')
    token = read_token(args.token_file)
    logging.getLogger('huggingface_hub').setLevel(logging.CRITICAL)
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
    api = HfApi(token=token)
    info = api.model_info(REPO)
    require(info.private is True, 'archive repository must be private')
    require(info.sha == args.expected_parent, 'HF head moved; expected-head guard refused the upload')
    require(not any(item.rfilename.startswith((PREFIX + 'source/', PREFIX + 'evidence/')) for item in info.siblings),
            'counterbalanced source/evidence archive already exists')
    with tempfile.TemporaryDirectory(prefix='jovovich-counterbalanced-evidence-') as cache:
        card = None
        if section is not None:
            original = hf_hub_download(REPO, 'README.md', revision=args.expected_parent, token=token,
                                       cache_dir=cache, force_download=True)
            card = Path(original).read_bytes()
            require(args.card_heading not in card.decode('utf-8'), 'model card already contains this experiment section')
            files['README.md'] = card + section
        expected = {name: dict(bytes=len(data), sha256=sha(data)) for name, data in files.items()}
        print(json.dumps(dict(phase='uploading', files=len(files), parent=args.expected_parent)), flush=True)
        commit = api.create_commit(REPO, parent_commit=args.expected_parent,
            commit_message='Archive counterbalanced review source and byte-preserved measured evidence',
            operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=data) for name, data in files.items()])
        require(re.fullmatch('[0-9a-f]{40}', commit.oid), 'upload returned an invalid commit ID')
        print(json.dumps(dict(phase='committed', commit=commit.oid, files=len(files))), flush=True)
        final = api.model_info(REPO, revision=commit.oid)
        require(final.private is True and final.sha == commit.oid, 'pinned archive state changed')
        def verify(item):
            name, metadata = item
            downloaded = hf_hub_download(REPO, name, revision=commit.oid, token=token,
                                         cache_dir=cache, force_download=True)
            data = Path(downloaded).read_bytes()
            require(len(data) == metadata['bytes'] and sha(data) == metadata['sha256'],
                    f'download verification failed: {name}')
            return dict(file=name, **metadata)
        verified = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for index, record in enumerate(pool.map(verify, expected.items()), 1):
                verified.append(record)
                if index % 8 == 0:
                    print(json.dumps(dict(phase='verifying', files=index, total=len(files))), flush=True)
        receipt = dict(repo=REPO, private=True, commit=commit.oid, parent_commit=args.expected_parent,
                       files_uploaded=len(files), verified_by_download=verified, verification_workers=4,
                       manifest_sha256=sha(files[PREFIX + 'evidence/manifest.json']),
                       prior_card_sha256=sha(card) if card is not None else None,
                       card_section_sha256=sha(section) if section is not None else None,
                       card_heading=args.card_heading if section is not None else None,
                       source_parent_commit=manifest['parent_commit'],
                       receipt_manifest_exclusion='Created after upload; excluded from the frozen manifest to avoid self-reference.')
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        for destination in (args.receipt, tracked_receipt):
            with destination.open('x') as target:
                json.dump(receipt, target, indent=2)
                target.write('\n')
        print(json.dumps(dict(phase='complete', commit=commit.oid, private=True, verified_files=len(verified),
                             receipt=str(args.receipt), tracked_receipt=str(tracked_receipt.relative_to(root)))), flush=True)


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        # HTTP exception text may contain signed URLs; never emit it.
        raise SystemExit(f'archive failed ({type(error).__name__}); inspect the recorded phase before retrying') from None
