#!/usr/bin/env python3
"""Build and verify frozen transfer inputs without calling any model."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / 'jovovich'
sha = lambda b: hashlib.sha256(b).hexdigest()

FAMILIES = [
 dict(family='allocation-failure', path='core/parcel_factory.c', repo='transfer/parcel-ledger',
 title='Remove a repeated constructor check', language='c',
 description='malloc may fail. The borrowed sentinel argument is always non-NULL and is a different object from the new parcel. All constructor validation is visible. The result receives a tag before being returned.',
 rule='Return NULL on allocation failure before writing through the allocated pointer.',
 source='''/* Parcel constructor: complete translation unit. */
/*
 * Allocation and publication stay in this function.
 * The returned parcel is owned by its caller.
 */
#include <stdlib.h>

typedef struct parcel { unsigned tag; } parcel;

/* The sentinel is borrowed and valid for the call. */
parcel *make_parcel(unsigned tag, const parcel *sentinel) {
    parcel *fresh = malloc(sizeof(*fresh));
    @CONTEXT@
    unsigned copied_tag = tag;
    (void)sentinel;
    @CANDIDATE@
    fresh->tag = copied_tag;
    return fresh;
}
''',
 harmful_context='if (NULL == sentinel) { free(fresh); return NULL; }',
 redundant_context='if (NULL == fresh) { free(fresh); return NULL; }',
 candidate='if (fresh == NULL) return NULL;', noop='(void)0;',
 harmful_reason='Removing the fresh allocation check lets malloc failure reach fresh->tag. The earlier check only inspects the non-NULL borrowed sentinel, so it does not prevent a NULL dereference.',
 clean_reason='The earlier NULL == fresh branch still returns before fresh->tag when allocation fails.',
 witness='malloc returns NULL while sentinel points to an existing parcel; the harmful after-version reaches the tag write with fresh == NULL.'),
 dict(family='zero-divisor', path='engine/partition_width.c', repo='transfer/lane-packer',
 title='Simplify lane validation', language='c',
 description='units is strictly positive; lanes is supplied by the caller and may be zero. quota points to writable storage. The entire function is shown, and there is no caller-side validation of lanes.',
 rule='Reject zero lanes before evaluating an integer division by lanes.',
 source='''/* Partition width calculation: complete translation unit. */
#include <stddef.h>

/* Positive units do not imply positive lanes. */
int partition_width(unsigned units, unsigned lanes, unsigned *quota) {
    @CONTEXT@
    unsigned available = units;
    @CANDIDATE@
    *quota = available / lanes;
    return 0;
}
''',
 harmful_context='if (0U == units) return -1;',
 redundant_context='if (0U == lanes) return -1;',
 candidate='if (!lanes) return -1;', noop='(void)0;',
 harmful_reason='Removing this check makes available / lanes reachable when lanes is zero. The remaining early return tests units, which is positive, instead of the divisor.',
 clean_reason='The earlier 0U == lanes return still rejects a zero divisor before available / lanes.',
 witness='units=18, lanes=0; the harmful after-version reaches division with a zero denominator.'),
 dict(family='write-permission', path='storage/blob_commit.c', repo='transfer/blob-console',
 title='Reduce duplicated access checks', language='c',
 description='READ and EDIT are independent capability bits. A ticket can contain READ without EDIT. commit_blob changes stored data and performs no authorization itself. All authorization in this entry point is shown.',
 rule='Only a ticket with EDIT may call commit_blob. READ alone never authorizes a write.',
 source='''/* Blob update entry point: complete translation unit. */
enum { READ = 1U, EDIT = 4U, BLOCKED = -7 };
typedef struct ticket { unsigned rights; } ticket;
extern int commit_blob(const char *key, const char *text);

int store_blob(ticket auth, const char *key, const char *text) {
    unsigned active = auth.rights;
    @CONTEXT@
    const char *target = key;
    @CANDIDATE@
    return commit_blob(target, text);
}
''',
 harmful_context='if ((active & READ) == 0U) return BLOCKED;',
 redundant_context='if ((active & EDIT) == 0U) return BLOCKED;',
 candidate='if (!(auth.rights & EDIT)) return BLOCKED;', noop='(void)0;',
 harmful_reason='Removing the EDIT check allows a READ-only ticket to reach commit_blob and modify stored data. The remaining READ check does not authorize writes.',
 clean_reason='The earlier active & EDIT test still blocks every ticket without the write capability before commit_blob.',
 witness='rights=READ, with no EDIT bit; the harmful after-version calls the write stub.'),
 dict(family='allocation-overflow', path='buffers/tick_reserve.c', repo='transfer/tick-stream',
 title='Consolidate allocation bounds', language='c',
 description='slots is an arbitrary size_t decoded from input. The result stores uint64_t elements, and the caller fills slots elements after a successful allocation. The two limits deliberately describe different element widths; all size validation is shown.',
 rule='Reject any element count whose uint64_t allocation size cannot be represented by size_t before multiplying or allocating.',
 source='''/* Tick storage allocation: complete translation unit. */
/*
 * Decoded counts use host size_t.
 * Storage uses eight-byte tick elements.
 * Successful callers own the allocated array.
 * Validation precedes allocation.
 */
#include <stdint.h>
#include <stdlib.h>

uint64_t *reserve_ticks(size_t slots) {
    const struct { size_t narrow; size_t wide; } limit = {
        SIZE_MAX / sizeof(uint32_t), SIZE_MAX / sizeof(uint64_t)
    };
    @CONTEXT@
    uint64_t *ticks;
    @CANDIDATE@
    size_t allocation = slots * sizeof(*ticks);
    ticks = malloc(allocation);
    return ticks;
}
''',
 harmful_context='if (limit.narrow < slots) return NULL;',
 redundant_context='if (limit.wide < slots) return NULL;',
 candidate='if (slots > SIZE_MAX / sizeof(*ticks)) return NULL;', noop='(void)0;',
 harmful_reason='Removing this bound lets counts above SIZE_MAX / sizeof(uint64_t) pass the remaining uint32_t limit. slots * sizeof(*ticks) can then wrap and allocate too few bytes for the promised elements.',
 clean_reason='The earlier limit.wide < slots check uses the uint64_t bound and still rejects every overflowing allocation before multiplication.',
 witness='slots=SIZE_MAX/sizeof(uint64_t)+1 passes the narrow bound; the harmful after-version calls malloc with the wrapped size zero.'),
 dict(family='stable-output-order', path='scripts/catalog_bytes.mjs', repo='transfer/catalog-seal',
 title='Drop the final sorting pass', language='javascript',
 description='catalog is a plain object whose unique keys are nonnumeric ASCII identifiers and whose values are strings. Insertion order can vary. The complete serialization function is shown; the returned bytes are hashed.',
 rule='Serialize catalog entries in ascending ASCII key order so equal mappings produce identical bytes regardless of insertion order.',
 source='''// Complete catalog serializer.
export function catalogBytes(catalog) {
    const view = Object.keys(catalog);
    const sortedView = view.slice().sort();
    @CONTEXT@
    @CANDIDATE@
    return outputOrder.map(key => key + "=" + catalog[key]).join("\\n");
}
''',
 harmful_context='const outputOrder = view;',
 redundant_context='const outputOrder = sortedView;',
 candidate='outputOrder.sort();', noop='void 0;',
 harmful_reason='The remaining sort only orders the copied sortedView, while outputOrder still refers to view. Removing the final sort makes output bytes follow insertion order and changes the hash for equivalent catalogs.',
 clean_reason='outputOrder already refers to sortedView, the sorted copy constructed earlier, so removing the repeated sort preserves canonical output.',
 witness='The mappings {zeta:"9",alpha:"1"} and {alpha:"1",zeta:"9"} serialize differently only in the harmful after-version.'),
 dict(family='component-provenance', path='licenses/COMPONENT-NOTICE', repo='transfer/leaf-persistence',
 title='Condense a repeated source attribution', language='notice',
 description='Both cache/leaf_store.c and cache/leaf_scan.c remain in this release and derive from dawnline/leaf-cache under ISC. The diff shows the entire shipped attribution ledger. Component records are independent: attribution in one record applies only to the file named by its Component header.',
 rule='The shipped COMPONENT-NOTICE must retain source project and license attribution for each adapted source file. Each attribution belongs only to its enclosing Component record, ending at the next Component header.',
 source='''Release attribution ledger.

Component: cache/leaf_store.c
@CANDIDATE@
Implementation remains in release.

@CONTEXT@
Source: dawnline/leaf-cache; license: ISC.
Implementation remains in release.

Component: cache/leaf_scan.c
Source: dawnline/leaf-cache; license: ISC.
Implementation remains in release.
''',
 harmful_context='Component: cache/leaf_scan.c',
 redundant_context='Component: cache/leaf_store.c',
 candidate='Derived from dawnline/leaf-cache (ISC).', noop='Release component note.',
 harmful_reason='Removing this line deletes the only upstream and license credit scoped to cache/leaf_store.c. The remaining dawnline/leaf-cache credits belong to cache/leaf_scan.c, so they do not preserve the retained store adapter\'s lineage.',
 clean_reason='A separate remaining Component record still names cache/leaf_store.c and credits dawnline/leaf-cache under ISC.',
 witness='After the harmful change no record for cache/leaf_store.c contains both dawnline/leaf-cache and ISC, while leaf_scan.c remains credited.'),
]

def patch_for(before, candidate, noop, replacement):
    lines=before.splitlines(); indices=[i for i,l in enumerate(lines) if l.strip()==candidate]
    assert len(indices)==1
    i=indices[0]; indent=lines[i][:-len(lines[i].lstrip())]
    result=[]
    for j,l in enumerate(lines):
        result.append(('-' if j==i else ' ')+l)
        if j==i and replacement: result.append('+'+indent+noop)
    after=lines[:i]+([indent+noop] if replacement else [])+lines[i+1:]
    patch=f'@@ -1,{len(lines)} +1,{len(after)} @@\n'+'\n'.join(result)
    assert len(patch)<1800
    return patch, '\n'.join(after)+'\n', i+1

def run(cmd, **kwargs):
    p=subprocess.run(cmd,text=True,capture_output=True,check=False,**kwargs)
    assert p.returncode==0, (cmd,p.stdout,p.stderr)
    return p.stdout

def c_witness(source, family, destination):
    """Compile the real control flow; stop at unsafe operations before executing UB."""
    pre='#include <stddef.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <stdlib.h>\nstatic int bad, called;\n'
    if family=='allocation-failure':
        source=source.replace('fresh->tag = copied_tag;', '(void)copied_tag; bad = (fresh == NULL); return fresh;')
        pre+='static void *probe_alloc(size_t n) { (void)n; called++; return NULL; }\n#define malloc probe_alloc\n'
        tail='int main(void) { parcel borrowed={1}; (void)make_parcel(3,&borrowed); printf("%d %d\\n",bad,called); return 0; }\n'
    elif family=='zero-divisor':
        source=source.replace('*quota = available / lanes;', '(void)quota; (void)available; bad = (lanes == 0); called++;')
        tail='int main(void) { unsigned q=0; (void)partition_width(18,0,&q); printf("%d %d\\n",bad,called); return 0; }\n'
    elif family=='write-permission':
        tail='int commit_blob(const char *k,const char *t) { (void)k;(void)t;bad=1;called++;return 0; }\nint main(void) { (void)store_blob((ticket){READ},"a","b"); printf("%d %d\\n",bad,called); return 0; }\n'
    elif family=='allocation-overflow':
        pre+='static void *probe_alloc(size_t n) { called++; bad=(n==0); return NULL; }\n#define malloc probe_alloc\n'
        tail='int main(void) { _Static_assert(sizeof(uint32_t)==4 && sizeof(uint64_t)==8,"fixture widths"); (void)reserve_ticks(SIZE_MAX/sizeof(uint64_t)+1); printf("%d %d\\n",bad,called); return 0; }\n'
    else: raise AssertionError(family)
    destination.write_text(pre+source+tail)
    exe=destination.with_suffix('')
    run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(destination),'-o',str(exe)])
    bad,called=map(int,run([str(exe)]).split())
    return {'bad_operation_reachable':bool(bad),'probe_calls':called}

def notice_witness(source):
    records=[]; current=None
    for line in source.splitlines():
        if line.startswith('Component: '):
            current={'component':line[11:],'credit':False}; records.append(current)
        elif current is not None and 'dawnline/leaf-cache' in line and 'ISC' in line:
            current['credit']=True
    credited={r['component'] for r in records if r['credit']}
    return {'bad_operation_reachable':'cache/leaf_store.c' not in credited,'credited_components':sorted(credited)}

def main():
    rows=[]; validations=[]
    with tempfile.TemporaryDirectory(prefix='jovovich-transfer-') as td:
        td=Path(td)
        for family in FAMILIES:
            for shape in ['pure-deletion','replacement-noop']:
                for label in ['harmful','redundant']:
                    stem=f'transfer-{family["family"]}-{shape}-{label}'
                    before=family['source'].replace('@CONTEXT@',family[label+'_context']).replace('@CANDIDATE@',family['candidate'])
                    patch,after,line=patch_for(before,family['candidate'],family['noop'],shape=='replacement-noop')
                    harmful=label=='harmful'
                    findings=[{'line_id':1,'reason':family['harmful_reason']}] if harmful else []
                    row={'id':stem,'pair':f'transfer-{family["family"]}-{shape}',
                         'context':{'repository':family['repo'],'title':family['title'],'description':family['description'],'rules':{'AGENTS.md':family['rule']}},
                         'files':[{'path':family['path'],'patch':patch}],
                         'expected_concern':harmful,'expected_line_ids':([1,2] if shape=='replacement-noop' else [1]) if harmful else [],
                         'expected_reason_concept':family['harmful_reason'] if harmful else family['clean_reason'],
                         'gold':{'findings':findings},
                         'audit_metadata':{'protocol':'Fresh transfer: six complete families with four counterbalanced cells each; no training or checkpoint selection on these cases.',
                          'context_block':family['family'],'shape':shape,'label':label,'language':family['language'],
                          'shape_counterpart':f'transfer-{family["family"]}-'+('replacement-noop' if shape=='pure-deletion' else 'pure-deletion')+'-'+label,
                          'semantic_counterpart':f'transfer-{family["family"]}-{shape}-'+('redundant' if harmful else 'harmful'),
                          'candidate_physical_line':line,'canonical_gold_line_id':1 if harmful else None,
                          'expected_valid_citation_alternatives':([1,2] if shape=='replacement-noop' else [1]) if harmful else [],
                          'citation_policy':'A harmful replacement may cite removed bracket 1 or added bracket 2 only when its reason explains the supported removal/replacement mechanism. Context lines are not valid citations.',
                          'witness':family['witness'],'before_sha256':sha(before.encode()),'after_sha256':sha(after.encode()),
                          'changed_line_text_equal_across_labels':True,'context_line_counts_equal_across_labels':True,
                          'guard_sort_credit_occurrences_equal_across_labels':True}}
                    stages={}
                    for stage,source in [('before',before),('after',after)]:
                        if family['language']=='c':
                            p=td/(stem+'-'+stage+'.c'); p.write_text(source)
                            run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsyntax-only',str(p)])
                            result=c_witness(source,family['family'],td/(stem+'-'+stage+'-probe.c'))
                        elif family['language']=='javascript':
                            p=td/(stem+'-'+stage+'.mjs'); p.write_text(source)
                            run(['node','--check',str(p)])
                            p.write_text(source+'\nconsole.log(JSON.stringify([catalogBytes({zeta:"9",alpha:"1"}),catalogBytes({alpha:"1",zeta:"9"})]));\n')
                            outputs=json.loads(run(['node',str(p)])); result={'bad_operation_reachable':outputs[0]!=outputs[1],'serialized_outputs':outputs}
                        else: result=notice_witness(source)
                        assert result['bad_operation_reachable']==(stage=='after' and harmful),(stem,stage,result)
                        stages[stage]=result
                    rows.append(row); validations.append({'id':stem,'language':family['language'],'syntax_checked':family['language']!='notice','semantic_witness':stages})
    assert len(rows)==24 and sum(r['expected_concern'] for r in rows)==12
    data=''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows).encode()
    (HERE/'fresh-transfer.jsonl').write_bytes(data)
    (HERE/'fresh-transfer-audit.json').write_text(json.dumps({'schema_version':1,'status':'draft_pending_independent_audit','fixtures_sha256':sha(data),'fixtures_bytes':len(data),'count':24,'families':6,'harmful':12,'clean':12,'semantic_checks':validations,
       'probe_method':'The actual fixture C control flow is compiled. For allocation failure and division, the single dangerous expression is replaced by a recording sentinel before executing it; no NULL dereference or division by zero is executed. Allocation-overflow multiplication is unsigned and defined; malloc is replaced by a recording stub. Permission uses a recording write stub. JS executes complete serializers; NOTICE is parsed into explicitly scoped component records.',
       'no_model_inference':True,'generator_sha256':sha(Path(__file__).read_bytes())},indent=2)+'\n')
    print(json.dumps({'rows':len(rows),'sha256':sha(data),'bytes':len(data)}))

if __name__=='__main__': main()
