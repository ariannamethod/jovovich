#!/usr/bin/env python3
"""Independent structural, production-parser, and controlled semantic audit."""
import collections
import hashlib
import json
import pathlib
import re
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = pathlib.Path.cwd()
FIXTURES = HERE / 'fresh-transfer.jsonl'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def run(args, **kw):
    p = subprocess.run(args, capture_output=True, text=True, **kw)
    assert p.returncode == 0, (args, p.stderr, p.stdout)
    return p.stdout

def source(patch, side):
    body = patch.splitlines()[1:]
    assert all(x and x[0] in ' +-' for x in body)
    return '\n'.join(x[1:] for x in body if x[0] in (' -' if side == 'before' else ' +')) + '\n'

def probe_c(src, family, tmp):
    original_src = src
    prefix = '#include <stdio.h>\n#include <stdlib.h>\n#include <stdint.h>\nstatic int audit_bad;\n'
    if family == 'allocation-failure':
        prefix += 'static int audit_fail;\nstatic void *audit_malloc(size_t n) { return audit_fail ? NULL : malloc(n); }\n'
        src = src.replace('malloc(', 'audit_malloc(')
        assert src.count('fresh->tag = copied_tag;') == 1
        src = src.replace('fresh->tag = copied_tag;', 'if (fresh == NULL) { audit_bad = 1; return NULL; } fresh->tag = copied_tag;')
        main = 'int main(void) { parcel sentinel = {3}; for (int f=0; f<2; f++) { audit_fail=f; audit_bad=0; parcel *p=make_parcel(17,&sentinel); if (!f && (!p || p->tag != 17)) return 2; printf("%d ",audit_bad); free(p); } return 0; }'
    elif family == 'zero-divisor':
        assert src.count('*quota = available / lanes;') == 1
        src = src.replace('*quota = available / lanes;', 'if (lanes == 0) { audit_bad = 1; return -2; } *quota = available / lanes;')
        main = 'int main(void) { unsigned q; audit_bad=0; (void)partition_width(18,0,&q); printf("%d ",audit_bad); audit_bad=0; int r=partition_width(18,3,&q); if (r || q != 6) return 2; printf("%d ",audit_bad); return 0; }'
    elif family == 'write-permission':
        main = 'static unsigned audit_rights; int commit_blob(const char *k,const char *v) { (void)k; (void)v; if (!(audit_rights & EDIT)) audit_bad=1; return 0; } int main(void) { unsigned rights[]={0,READ,EDIT,READ|EDIT}; for(unsigned i=0;i<4;i++) { audit_bad=0; audit_rights=rights[i]; ticket t={rights[i]}; (void)store_blob(t,"key","value"); printf("%d ",audit_bad); } return 0; }'
    elif family == 'allocation-overflow':
        prefix += 'static size_t audit_size; static int audit_calls; static void *audit_malloc(size_t n) { audit_size=n; audit_calls++; return NULL; }\n'
        src = src.replace('malloc(', 'audit_malloc(')
        main = 'int main(void) { size_t wide=SIZE_MAX/sizeof(uint64_t), narrow=SIZE_MAX/sizeof(uint32_t); size_t counts[]={0,3,wide,wide+1,narrow,narrow+1}; for(unsigned i=0;i<6;i++) { audit_calls=0; (void)reserve_ticks(counts[i]); int bad=audit_calls && counts[i]>wide; if (audit_calls && audit_size != counts[i]*sizeof(uint64_t)) return 2; printf("%d ",bad); } return 0; }'
    else:
        raise AssertionError(family)
    original = tmp / 'original.c'
    original.write_text(original_src)
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-fsyntax-only', str(original)])
    transformed = tmp / 'probe.c'
    transformed.write_text(prefix + src + '\n' + main + '\n')
    binary = tmp / 'probe'
    run(['cc', '-std=c11', '-O0', '-Wall', '-Wextra', str(transformed), '-o', str(binary)])
    return [int(x) for x in run([str(binary)]).split()]

raw = FIXTURES.read_bytes()
rows = [json.loads(x) for x in raw.splitlines()]
assert len(rows) == 24 and len({r['id'] for r in rows}) == 24
by_id = {r['id']: r for r in rows}
observations = []
with tempfile.TemporaryDirectory(prefix='jovovich-independent-transfer-') as td:
    tmp = pathlib.Path(td)
    for row in rows:
        patch = row['files'][0]['patch']
        before, after = source(patch, 'before'), source(patch, 'after')
        h = re.fullmatch(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', patch.splitlines()[0])
        assert h and tuple(map(int,h.groups())) == (1,len(before.splitlines()),1,len(after.splitlines()))
        meta = row['audit_metadata']; family=meta['context_block']
        assert sha(before.encode()) == meta['before_sha256']
        assert sha(after.encode()) == meta['after_sha256']
        other=by_id[meta['semantic_counterpart']]
        assert row['context'] == other['context']
        assert row['files'][0]['path'] == other['files'][0]['path']
        changes = [x for x in patch.splitlines()[1:] if x.startswith(('+','-'))]
        assert changes == [x for x in other['files'][0]['patch'].splitlines()[1:] if x.startswith(('+','-'))]
        assert len(patch.splitlines()) == len(other['files'][0]['patch'].splitlines())
        count_pattern = r'\bif\s*\(' if meta['language']=='c' else (r'\.sort\(' if meta['language']=='javascript' else 'dawnline/leaf-cache')
        assert len(re.findall(count_pattern,patch)) == len(re.findall(count_pattern,other['files'][0]['patch']))
        semantic = {}
        for side, src in [('before',before),('after',after)]:
            if meta['language'] == 'c':
                vals=probe_c(src,family,tmp)
                semantic[side]={'unsafe_reachability':any(vals),'per_input_flags':vals}
            elif meta['language'] == 'javascript':
                module=tmp/'case.mjs'; module.write_text(src)
                run(['node','--check',str(module)])
                js='import {catalogBytes} from '+json.dumps(module.as_uri())+'; const pairs=[["zeta","9"],["alpha","1"],["middle","4"]]; let out=[]; for(const ix of [[0,1,2],[1,2,0],[2,0,1],[2,1,0]]) out.push(catalogBytes(Object.fromEntries(ix.map(i=>pairs[i])))); process.stdout.write(JSON.stringify(out));'
                outputs=json.loads(run(['node','--input-type=module','-e',js]))
                semantic[side]={'unsafe_reachability':len(set(outputs))!=1,'serialized_outputs':outputs}
            else:
                credits=collections.defaultdict(list); component=None
                for line in src.splitlines():
                    if line.startswith('Component: '): component=line.split(': ',1)[1]
                    elif component and 'dawnline/leaf-cache' in line and 'ISC' in line: credits[component].append(line)
                covered={x:bool(credits[x]) for x in ['cache/leaf_store.c','cache/leaf_scan.c']}
                semantic[side]={'unsafe_reachability':not all(covered.values()),'component_coverage':covered}
        assert not semantic['before']['unsafe_reachability']
        assert semantic['after']['unsafe_reachability'] == row['expected_concern']
        observations.append({'id':row['id'],'semantic_label_correct':True,'hunk_counts_correct':True,'source_hashes_match':True,'context_and_changed_lines_balanced':True,'guard_sort_credit_counts_balanced':True,'semantic':semantic})

node_script = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {chunksFor,parseReview,promptFor} from './bin/jovovich.mjs';
const rows=JSON.parse(fs.readFileSync(0,'utf8'));
const identity=fs.readFileSync('prompts/identity.txt','utf8');
const out=[];
for(const r of rows) {
  const chunks=chunksFor(r.files); assert.equal(chunks.length,1);
  const c=chunks[0]; assert.equal(c.surrounding_diff,r.files[0].patch);
  assert.equal(c.lines[0].side,'LEFT'); assert.equal(c.lines[0].line,r.audit_metadata.candidate_physical_line);
  const parsed=parseReview(JSON.stringify(r.gold),c); assert.equal(parsed.findings.length,r.expected_concern?1:0);
  if(r.expected_concern) {assert.equal(parsed.findings[0].quote,c.lines[0].quote);assert.equal(parsed.findings[0].line,c.lines[0].line);}
  if(r.audit_metadata.shape==='replacement-noop') {assert.equal(c.lines.length,2);assert.equal(c.lines[1].side,'RIGHT');assert.equal(c.lines[1].line,c.lines[0].line); if(r.expected_concern) parseReview(JSON.stringify({findings:[{line_id:2,reason:r.expected_reason_concept}]}),c);}
  else assert.equal(c.lines.length,1);
  const p=await promptFor(c,r.context,identity,'chatml');
  assert(!p.includes(r.id));assert(!p.includes('expected_concern'));assert(!p.includes('audit_metadata'));
  out.push({id:r.id,gold_production_parse:true,changed_line_ids:c.lines.map((_,i)=>i+1),candidate_physical_line:c.lines[0].line,untruncated_diff:true,prompt_bytes:Buffer.byteLength(p)});
}
process.stdout.write(JSON.stringify(out));
'''
production=json.loads(run(['node','--input-type=module','-e',node_script],cwd=REPO,input=json.dumps(rows)))
for a,b in zip(observations,production):
    assert a['id']==b['id']; a['production']=b
training_path=REPO/'training/sft_review_v4.jsonl'
training=[json.loads(x) for x in training_path.read_text().splitlines()]
prior_user=[m['content'] for r in training for m in r['messages'] if m['role']=='user']
prior_diffs=[x.split('Surrounding diff:\n',1)[1].split('\n\nChanged lines to review:',1)[0] for x in prior_user if 'Surrounding diff:\n' in x]
prior_coordinates=set(int(n) for x in prior_user for n in re.findall(r'^\[\d+\] (?:ADDED|REMOVED) [^\n]+?:(\d+):',x,re.M))
novelty=[]
for family in sorted({r['audit_metadata']['context_block'] for r in rows}):
    r=next(r for r in rows if r['audit_metadata']['context_block']==family)
    path=r['files'][0]['path']
    assert all(path not in x for x in prior_user)
    assert r['audit_metadata']['candidate_physical_line'] not in prior_coordinates
    assert all(c['files'][0]['patch'] not in prior_diffs for c in rows if c['audit_metadata']['context_block']==family)
    novelty.append({'family':family,'new_path':path,'candidate_physical_line':r['audit_metadata']['candidate_physical_line'],'path_absent_from_v4':True,'coordinate_absent_from_v4':True,'all_family_diffs_absent_from_v4':True})
assert FIXTURES.read_bytes()==raw
report={
 'schema_version':1,'status':'pass','auditor':'independent subagent; did not edit fixtures or reuse builder witness implementation',
 'fixtures':{'path':str(FIXTURES),'sha256':sha(raw),'bytes':len(raw)},
 'audit_script_sha256':sha(pathlib.Path(__file__).read_bytes()),
 'production_source_sha256':sha((REPO/'bin/jovovich.mjs').read_bytes()),
 'training_overlap_source':{'path':str(training_path),'sha256':sha(training_path.read_bytes())},
 'no_model_inference':True,'reviewed_all_cases':24,
 'counts':{'families':6,'semantic_pairs':12,'harmful':12,'clean':12,'before_after_semantic_checks':48,'native_c_versions':32,'javascript_versions':8,'notice_versions':8,'production_gold_parses':24,'replacement_alternate_citations':6},
 'semantic_method':'Fresh native wrappers preserve every guard/control path, intercept only NULL dereference and zero division before undefined behavior, replace allocation with an observation stub for huge sizes, and stub commit_blob to record unauthorized calls. Exact JavaScript runs on four insertion orders. Explicit NOTICE component records are parsed by independently written code.',
 'family_review':{
  'allocation-failure':'The harmful remaining NULL comparison is against a supplied non-NULL sentinel; the redundant comparison tests fresh with reversed spelling before the tag write.',
  'zero-divisor':'The harmful remaining comparison checks positive units; the redundant comparison checks the divisor lanes before division.',
  'write-permission':'READ cannot authorize EDIT; the retained alias active is unchanged and its EDIT test is equivalent to the removed auth.rights test.',
  'allocation-overflow':'The uint32_t threshold permits counts that overflow uint64_t allocation; the retained uint64_t threshold is equivalent to the removed bound.',
  'stable-output-order':'Sorting a copy does not order the original view. Only the redundant outputOrder alias points at the sorted copy.',
  'component-provenance':'The explicit record-scoping rule binds remaining credits to their named file. Only the redundant ledger retains an alternate credit for leaf_store.c.'},
 'lexical_controls':'Equal changed lines, context lengths, if/sort/credit counts within opposite-label pairs verified. Family paths and context/rules are identical across cells. Metadata and labels are excluded by production prompt construction.',
 'coordinate_note':'All six candidate physical coordinates are absent from v4 changed-line coordinates (11,12,13); coordinates remain balanced across all four cells within each family.',
 'overlap':'Transfer preserves six trained defect families and host/system framing, with new repositories, paths, local symbols and alternative-protection dataflow. All six paths and all24 full diff strings are absent from v4. This is fresh-context transfer within familiar defect families.',
 'novelty':novelty,'cases':observations,
 'findings':[]}
(HERE/'fresh-transfer-independent-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':'pass','fixtures_sha256':sha(raw),'report_sha256':sha((HERE/'fresh-transfer-independent-audit.json').read_bytes()),'counts':report['counts']}))
