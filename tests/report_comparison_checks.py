"""Report/history transactions on synthetic receipts; no model inference."""
import copy
import hashlib
import json
import resource
import signal
import struct
import subprocess
import zlib
from concurrent.futures import ThreadPoolExecutor

from check_visual_batch import ROOT, command, encode
from check_visual_memory import ENV


def check_report_comparisons(report, replay, work, visual, cases):
    memory=work/'report-context';memory.mkdir()
    original={p.name:p.read_bytes() for p in visual.glob('*.checkpoint')}
    first,updated,west,other_pr,image_only=cases

    def snapshots(): return {p.name:p.read_bytes() for p in memory.glob('*.checkpoint')}

    def argv(case, markdown=False, compare=True):
        return [report,case['batch'],case['answers'],'--with-visual',visual,case['scope'],case['pr'],
                '--memory',memory,'--record-pr',case['scope'],case['metadata'],
                *([] if markdown else ['--json']),*(['--compare-previous'] if compare else [])]

    def publish(case, markdown=False, ok=True, extra=()):
        return command([*argv(case,markdown),*extra],ok=ok)

    def history(case):
        return json.loads(command([replay,'history',memory,case['scope'],case['pr']]))['observations']

    outputs=[]
    for i,case in enumerate(cases):
        raw=publish(case);result=json.loads(raw);outputs.append(raw)
        assert result['review_observation']['ordinal']==(2 if i==1 else 1)
        rows=history(case);saved=rows[-1]['evidence']['review']
        assert [f['answer'] for f in saved['files']]==[json.loads(x) for x in case['votes'].splitlines()]
        if i==1:
            cmp=result['review_comparison'];assert cmp['before']['observation']==rows[0] and cmp['after']['observation']==rows[1]
            pair=[cmp[side]['observation_id'] for side in ('before','after')]
            standalone=command([replay,'reviews',memory,case['scope'],case['pr'],'--compare',*pair])
            assert json.loads(standalone)==cmp
            assert [f['transition'] for f in cmp['files']]==['unchanged_clean','not_comparable']
        else: assert result['review_comparison'] is None
        plain=json.loads(command(argv(case,compare=False)))
        assert {k:v for k,v in result.items() if k not in ('review_observation','review_comparison')}==plain
        stable=snapshots();md=publish(case,markdown=True)
        assert b'## Since the previous review' in md
        if i==1:
            assert b'| panel\\.html | CLEAN | CLEAN | Still CLEAN |' in md
            assert b'| screen\\.ppm | CONCERN | CLEAN | Conditions changed: policy |' in md
        else: assert b'No earlier mixed review in this PR.' in md
        assert publish(case)==raw and publish(case,markdown=True)==md and snapshots()==stable

    # A fresh evaluation at the same head appends once; retries keep the original predecessor.
    third=dict(updated,answers=work/'third.answers')
    answers=[json.loads(x) for x in updated['votes'].splitlines()]
    answers[0]['execution']['reviewed_at']['millisecond']=(answers[0]['execution']['reviewed_at']['millisecond']+1)%1000
    third['answers'].write_text(''.join(encode(x)+'\n' for x in answers))
    with ThreadPoolExecutor(max_workers=3) as pool:
        retries=list(pool.map(lambda _:publish(third),range(3)))
    assert len(set(retries))==1
    third_result=json.loads(retries[0]);assert third_result['review_observation']['ordinal']==3
    assert third_result['review_comparison']['before']['observation_id']==json.loads(outputs[1])['review_observation']['observation_id']
    assert publish(updated)==outputs[1] and publish(first)==outputs[0]
    assert len(history(first))==3
    first_row,second_row=history(first)[:2]
    journal=memory/('pr-'+hashlib.sha256(first['scope'].encode()).hexdigest()+'-7.checkpoint')

    def store(rows):
        return command([ROOT/'build/review-history-fixture',journal,first['scope'],7],
                       ''.join(encode(r)+'\n' for r in rows).encode())

    legacy=copy.deepcopy(first_row);del legacy['evidence']['review']
    store([first_row,legacy]);result=json.loads(publish(updated))
    assert result['review_observation']['ordinal']==3 and result['review_comparison']['before']['ordinal']==1
    store([legacy]);result=json.loads(publish(updated))
    assert result['review_observation']['ordinal']==2 and result['review_comparison'] is None

    # Changed identities and a path no longer in the current manifest are visible in both formats.
    previous=copy.deepcopy(first_row)
    files=previous['evidence']['review']['files'];text=files[0]
    path='old|name`<x>.html';text['file']=text['input']['file']=text['answer']['scope']['file']=path
    files[1]['answer']['weights_sha256']='a'*64
    store([previous]);result=json.loads(publish(updated));cmp=result['review_comparison']
    assert [f['transition'] for f in cmp['files']]==['not_reviewed_after','not_comparable','first_review']
    assert cmp['files'][0]['after'] is None and cmp['files'][2]['before'] is None
    assert cmp['files'][1]['reasons']==['model_changed','policy_changed']
    md=publish(updated,markdown=True)
    assert b'Not reviewed this time' in md and b'First review' in md and b'Conditions changed: model, policy' in md
    assert '| old\\|name\\`&lt;x&gt;\\.html | CLEAN | — | Not reviewed this time |'.encode() in md

    # Failure before commit: intact container with an invalid evidence digest, including hidden review.
    for before,after in [(b'"verdict":"CONCERN"',b'"verdict":"CLEAN  "'),(b'"review":',b'"hidden":')]:
        store([first_row]);raw=journal.read_bytes();damaged=bytearray(raw.replace(before,after,1));assert raw!=damaged
        struct.pack_into('<I',damaged,28,zlib.crc32(damaged[:28]+damaged[32:]));journal.write_bytes(damaged)
        stable=snapshots()
        for markdown in (False,True):publish(updated,markdown,ok=False)
        assert snapshots()==stable
    malformed=copy.deepcopy(first_row);malformed['evidence']['review']['summary']['reviewed_files']=99
    for rows in ([malformed],[first_row,first_row]):
        store(rows);stable=snapshots();publish(updated,ok=False);assert snapshots()==stable

    def limited(limit,commit_failure):
        def restrict():
            resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit));signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
        stable=snapshots()
        p=subprocess.run([str(x) for x in argv(updated)],cwd=ROOT,env=ENV,capture_output=True,preexec_fn=restrict)
        assert p.returncode!=0 and not p.stdout,(p.returncode,p.stdout,p.stderr)
        if commit_failure: assert b'save before commit failed' in p.stderr,p.stderr
        assert snapshots()==stable

    store([first_row]);plain=command(argv(updated,compare=False));store([first_row])
    limited(len(plain)+100,False)
    padded=copy.deepcopy(legacy);padded['evidence']['padding']='x'*100000
    store([first_row,padded]);limited(journal.stat().st_size+128,True)
    store([first_row]);stable=snapshots()
    publish(updated,ok=False,extra=['--compare-previous'])
    for command_line in ([report,first['batch'],first['answers'],'--compare-previous'],
                         [report,first['batch'],first['answers'],'--with-visual',visual,first['scope'],7,'--compare-previous']):
        command(command_line,ok=False)
    assert snapshots()==stable
    assert {p.name:p.read_bytes() for p in visual.glob('*.checkpoint')}==original
    print('PASS: report comparisons, exact prior receipts, concurrent/idempotent retries, later appends, scope isolation, legacy rows, escaped paths and atomic render/commit rejection')
