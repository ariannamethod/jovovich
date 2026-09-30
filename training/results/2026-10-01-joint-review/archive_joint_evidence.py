"""Validate the frozen joint-review manifest; --upload archives its allowlists privately."""
import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import tempfile


REPO = 'ataeff/jovovich'
RESULTS = 'training/results/2026-10-01-joint-review'
PREFIX = 'experiments/joint-review/'
HEADING = '## Complete-review joint objective (2026-10-01)'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(directory, name, expected=None):
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'manifest path must be a canonical relative path')
    local = directory / name
    require(local.resolve().is_relative_to(directory.resolve()) and local.is_file(), f'missing or external manifest file: {name}')
    data = local.read_bytes()
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
            require(not name.endswith(('.gguf', '.lora', '.f32')), 'weight files use their separate archive')
            require(remote + name not in files, 'duplicate archive path')
            files[remote + name] = checked_file(base, name, digest)
    require(PREFIX + 'evidence/manifest.json' not in files, 'manifest must not hash itself')
    files[PREFIX + 'evidence/manifest.json'] = manifest_bytes
    for name in ('training/train_mlp.c', 'src/infer.c', 'training/sft_review_v2.jsonl', 'training/review_holdout_v2.jsonl'):
        require(PREFIX + 'source/' + name in files, f'required source missing: {name}')
    require(sha(files[PREFIX + 'evidence/infer-experiment.c']) == manifest['experiment_inference']['sha256'], 'experiment inference snapshot mismatch')
    require(manifest['training']['objective'] == 'joint' and manifest['runtime_model_promoted'] is False, 'unexpected experiment')
    scores = json.loads(files[PREFIX + 'evidence/scores.json'])
    summary = json.loads(files[PREFIX + 'evidence/generation-summary.json'])
    semantics = json.loads(files[PREFIX + 'evidence/semantic-assessment.json'])
    require(semantics.get('complete') is True, 'manual semantic assessment is incomplete')
    chosen = scores['selected']
    require(scores['selected_update'] == manifest['selected_model']['update'] and
            scores['selected_update'] in (25, 50, 100), 'checkpoint selection disagrees')
    require(scores['metrics_sha256'] == sha(files[PREFIX + 'evidence/metrics.jsonl']), 'score provenance mismatch')
    joint, control = summary['cohorts']['joint'], summary['cohorts']['control']
    for arm, cohorts in summary['cohorts'].items():
        for name, cohort in cohorts.items():
            judged = semantics['cohorts'][arm][name]['counts']
            measured = cohort['counts']
            require(judged['cases'] == measured['cases'] and
                    0 <= judged['grounded_concern_reviews'] <= measured['expected_concerns'] and
                    judged['grounded_concern_reviews'] <= judged['genuine_issues_detected'] <= measured['expected_concerns'] and
                    0 <= judged['correct_clean_reviews'] <= measured['expected_clean'] and
                    0 <= judged['full_review_pairs'] <= measured['pairs'] and
                    judged['full_reviews_pass'] == judged['grounded_concern_reviews'] + judged['correct_clean_reviews'],
                    f'manual semantic counts disagree: {arm}/{name}')
    for cohorts in (joint, control):
        for cohort in cohorts.values():
            require(cohort['counts']['cases'] == len(cohort['cases']), 'generation summary count mismatch')
    require(summary['protocol']['generated_responses'] == 164, 'generation total mismatch')
    counts = manifest['result_counts']
    require(counts['main_generated_responses'] == 164 and counts['matched_generated_responses'] == 8 and
            counts['generated_responses'] == 172, 'main/matched archive totals disagree')
    matched = [json.loads(line) for line in files[PREFIX + 'evidence/matched-shape-control.jsonl'].splitlines()]
    matched_plan = json.loads(files[PREFIX + 'evidence/matched-shape-plan.json'])
    require(len(matched) == len({row['name'] for row in matched}) == 8 and
            [row['name'] for row in matched] == matched_plan['case_ids'], 'incomplete matched-shape archive')
    require(all(row['model_sha256'] == control['train-shared']['model_sha256'] and row['returncode'] == 0 and
                row['infer_source_sha256'] == manifest['experiment_inference']['sha256'] and
                row['runner_sha256'] == manifest['experiment_inference']['runner_sha256'] for row in matched),
            'matched-shape model/runtime provenance mismatch')
    json.loads(files[PREFIX + 'evidence/matched-shape-summary.json'])
    train, diagnostic = joint['train-natural']['counts'], joint['diagnostics-natural']['counts']
    train_semantic = semantics['cohorts']['joint']['train-natural']['counts']
    diagnostic_semantic = semantics['cohorts']['joint']['diagnostics-natural']['counts']
    previous_shared, current_shared = control['train-shared']['counts'], joint['train-shared']['counts']
    section = (
        f'\n\n{HEADING}\n\n'
        'The fresh native notorch run adds the mean CE over 792 remaining review-answer targets '
        'to the existing mean CE over 40 paired decision targets. It uses the fixed v2 corpus, '
        '100 Adam updates and learning rate 0.0001. '
        f'The unchanged selector chose update {scores["selected_update"]}, with '
        f'{chosen["correct_targets"]}/40 teacher-forced target wins and '
        f'{chosen["complete_decision_pairs"]}/20 complete token-decision pairs. '
        f'Decision CE is {chosen["mean_decision_ce"]:.8f}; residual CE is '
        f'{chosen["mean_residual_ce"]:.8f}.\n\n'
        f'Natural joint-model generation produced {train["production_parse"]}/40 parser-accepted '
        f'training reviews and {diagnostic["production_parse"]}/12 parser-accepted diagnostic reviews. '
        f'The corresponding complete usable presence-pair counts are '
        f'{train["complete_usable_presence_pairs"]}/20 and {diagnostic["complete_usable_presence_pairs"]}/6. '
        f'Shared-prefix parser acceptance is {previous_shared["production_parse"]}/40 for the '
        f'smaller-step comparator and {current_shared["production_parse"]}/40 for the joint model. '
        f'Manual review detects {train_semantic["genuine_issues_detected"]}/20 genuine training issues, '
        f'with {train_semantic["grounded_concern_reviews"]}/20 fully grounded '
        f'training concern reviews and {diagnostic_semantic["grounded_concern_reviews"]}/6 '
        f'fully grounded diagnostic concern reviews; complete correct pairs are '
        f'{train_semantic["full_review_pairs"]}/20 and {diagnostic_semantic["full_review_pairs"]}/6. '
        'Complete responses, native emitted-token traces, diff-shape audits and manual causal assessments '
        'accompany these measurements. Eight additional matched-template control continuations bring the '
        'archive to 172 responses; their raw evidence is `experiments/joint-review/evidence/matched-shape-control.jsonl` '
        'and their separate assessment is `experiments/joint-review/evidence/matched-shape-summary.json`.\n\n'
        'Manifest-listed source snapshots are under `experiments/joint-review/source/`; '
        'the preserved inference source used for this experiment and all evidence are under '
        '`experiments/joint-review/evidence/`. Evidence bytes and recorded runtime paths are preserved. '
        'The production model lock continues to identify the base checkpoint.\n'
    )
    return manifest, files, section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-parent', required=True, help='exact current private HF commit')
    parser.add_argument('--upload', action='store_true', help='commit and download-verify; default validates locally')
    parser.add_argument('--token-file', type=Path, default=Path('../recovered/4astra.txt'))
    parser.add_argument('--receipt', type=Path, default=Path('models/joint-review-hf-evidence.json'))
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{40}', args.expected_parent), 'expected-parent must be a full commit SHA')
    root = Path.cwd().resolve()
    manifest, files, section = collect(root)
    if not args.upload:
        print(json.dumps(dict(phase='local_validation_only', repo=REPO, files=len(files),
                             manifest_sha256=sha(files[PREFIX + 'evidence/manifest.json']), expected_parent=args.expected_parent)))
        return
    tracked_receipt = root / RESULTS / 'hf-evidence.json'
    require(not args.receipt.exists() and not tracked_receipt.exists(), 'archive receipt already exists')
    require('hf-evidence.json' not in manifest['evidence_sha256'], 'receipt must stay outside the frozen manifest')
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
    require(info.private, 'archive repository must be private')
    require(info.sha == args.expected_parent, 'HF head moved; expected-parent guard refused the upload')
    require(not any(item.rfilename.startswith((PREFIX + 'source/', PREFIX + 'evidence/')) for item in info.siblings),
            'joint source/evidence archive already exists')
    with tempfile.TemporaryDirectory(prefix='jovovich-joint-archive-') as cache:
        original = hf_hub_download(REPO, 'README.md', revision=args.expected_parent, token=token,
                                   cache_dir=cache, force_download=True)
        card = Path(original).read_bytes()
        require(HEADING not in card.decode('utf-8'), 'model card already contains this experiment section')
        files['README.md'] = card + section.encode('utf-8')
        expected = {name: dict(bytes=len(data), sha256=sha(data)) for name, data in files.items()}
        print(json.dumps(dict(phase='uploading', files=len(files), parent=args.expected_parent)), flush=True)
        commit = api.create_commit(REPO, parent_commit=args.expected_parent,
            commit_message='Archive joint-review source, unchanged evidence and measured model-card results',
            operations=[CommitOperationAdd(path_in_repo=name, path_or_fileobj=data) for name, data in files.items()])
        print(json.dumps(dict(phase='committed', commit=commit.oid, files=len(files))), flush=True)
        require(api.model_info(REPO, revision=commit.oid).private, 'archive privacy changed')
        def verify(item):
            name, metadata = item
            downloaded = hf_hub_download(REPO, name, revision=commit.oid, token=token,
                                         cache_dir=cache, force_download=True)
            data = Path(downloaded).read_bytes()
            require(len(data) == metadata['bytes'] and sha(data) == metadata['sha256'], f'download verification failed: {name}')
            return dict(file=name, **metadata)
        verified = []
        # Files are independent reads of one immutable revision; preserve the
        # allowlist order in the receipt while overlapping network latency.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for index, record in enumerate(pool.map(verify, expected.items()), 1):
                verified.append(record)
                if index % 8 == 0:
                    print(json.dumps(dict(phase='verifying', files=index, total=len(files))), flush=True)
        receipt = dict(repo=REPO, private=True, commit=commit.oid, parent_commit=args.expected_parent,
                       files_uploaded=len(files), verified_by_download=verified, verification_workers=4,
                       manifest_sha256=sha(files[PREFIX + 'evidence/manifest.json']), prior_card_sha256=sha(card),
                       card_heading=HEADING, source_parent_commit=manifest['parent_commit'],
                       receipt_manifest_exclusion='Created after upload; excluded from the frozen manifest to avoid self-reference.')
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
        # HTTP exception text may contain signed URLs; credentials and those URLs stay out of output.
        raise SystemExit(f'archive failed ({type(error).__name__}); inspect state before retrying') from None
