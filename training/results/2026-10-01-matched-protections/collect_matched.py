#!/usr/bin/env python3
"""Archive completed data/token/semantic gates and the unexecuted training design."""
import argparse, hashlib, json, re
from pathlib import Path

TOP_FILES=['protocol.json','protocol-review.json','reproduction.json','procedural-attempts.json','prepare_archive.py','collect_matched.py',
 'v5-builder-audit.json','holdout-builder-audit.json','independent-v5-audit-final.json','independent-v5-design-metadata-audit.json','independent-v5-audit.json','independent-holdout-audit.json',
 'independent_v5_audit.py','independent_holdout_audit.py','independent-token-evidence-audit.json','independent-holdout-projection-audit.json','independent_token_evidence_audit.py','independent_holdout_projection_audit.mjs','integrity-audit.json','copilot-findings.json',
 'native-matching-summary.json','v4-v5-token-comparison.json','v4-archived-parity.json','token_audit.py',
 'token_audit_candidate_v1.py','token_audit_candidate_v2.py','project_holdout_tokens.mjs','holdout-token-source.jsonl',
 'review_v5_design.before-native-receipt.json','design-metadata-completion.json','Makefile.before-test-dependency','makefile-test-dependency.json','tests-clean-readout-cli.txt','preflight_matched.py','preflight-build.json','preflight-build.stdout','preflight-build.stderr','tests.txt',
 'holdout_candidate_search.py','holdout-erase-candidates.jsonl']
DIRS=['v4-token-final','v5-token-final','holdout-token-final','v5-native','v5-native-v2','holdout-v5-native','holdout-v5-native-v2',
 'holdout-token-candidate-1','holdout-erase-candidate-audit']+[f'candidate-audit-{i}' for i in range(1,6)]
SOURCES=['training/build_review_v4.mjs','training/sft_review_v3.jsonl','training/results/2026-10-01-joint-review/joint-next-control.json','training/results/2026-10-01-counterbalanced-review/fresh-transfer.jsonl','training/results/2026-10-01-joint-review/joint-diagnostics-natural.jsonl','training/build_review_v5.mjs','training/build_holdout_v5.mjs','training/review_v5_design.json',
 'training/holdout_v5_design.json','training/sft_review_v4.jsonl','training/sft_review_v5.jsonl','training/review_holdout_v5.jsonl',
 'training/review_holdout_v2.jsonl','training/prepare.py','training/score_decisions.py','training/train_mlp.c',
 'training/extract_readout.c','training/probe_tokenization.c','training/evaluate_review.mjs','training/evaluate.py',
 'training/merge_mlp.c','training/probe_mlp.c','training/export_adapter.c','bin/jovovich.mjs','prompts/identity.txt',
 'src/infer.c','model.json','Makefile','test/review_v5.test.mjs','test/holdout_v5.test.mjs','test/readout_workflow.test.mjs',
 'training/results/2026-10-01-counterbalanced-review/probe_counterbalanced.c',
 'training/results/2026-10-01-counterbalanced-review/plan.json','training/results/2026-10-01-counterbalanced-review/hf-weights.json',
 'training/results/2026-10-01-counterbalanced-review/selected-model.json']

def require(value,message):
 if not value:raise ValueError(message)
def sha(data):return hashlib.sha256(data).hexdigest()
HASH_CACHE={}
def record(path):
 path=path.resolve();stat=path.stat();key=(str(path),stat.st_size,stat.st_mtime_ns)
 if key in HASH_CACHE:return dict(HASH_CACHE[key])
 digest=hashlib.sha256();size=0
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):digest.update(block);size+=len(block)
 require(path.stat().st_mtime_ns==stat.st_mtime_ns and size==stat.st_size,'file changed during hash')
 result={'sha256':digest.hexdigest(),'bytes':size};HASH_CACHE[key]=result;return dict(result)
def load(path):return json.loads(path.read_bytes())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 root,ref,out=(x.resolve() for x in (a.repo,a.reference,a.out));require(not out.exists(),'archive already exists')
 sources=set(SOURCES);sources.update(str(p.relative_to(root)) for p in (root/'training/readout').glob('*') if p.is_file())
 payload={};origins={};omissions={};historical=[]
 def add(path,name=None):
  path=path.resolve();name=name or path.relative_to(ref).as_posix();relative=Path(name)
  require(not relative.is_absolute() and '..' not in relative.parts and name!='manifest.json','unsafe archive path')
  data=path.read_bytes();require(not data.startswith(b'\x7fELF'),'compiled executables are not archived')
  require(not re.search(rb'hf_[A-Za-z0-9]{20,}',data),'credential-like input')
  if name in payload:require(payload[name]==data,'archive name collision')
  else:payload[name]=data;origins[name]=str(path)
 for name in TOP_FILES:add(ref/name)
 for i in range(1,6):
  for name in (f'candidate-history-{i}.json',f'candidate-prompts-{i}.jsonl','candidate_token_search'+('' if i==1 else '_'+str(i))+'.py'):add(ref/name)
 for directory in DIRS:
  for path in sorted((ref/directory).iterdir()):
   require(path.is_file(),'unexpected nested artifact');add(path)
 # Resolve historical sidecar paths by bytes; never rewrite old receipts.
 version_paths={record(ref/name)['sha256']:ref/name for name in ['token_audit_candidate_v1.py','token_audit_candidate_v2.py','Makefile.before-test-dependency','review_v5_design.before-native-receipt.json']}
 def binding(item,context):
  path=Path(item['path']);path=path if path.is_absolute() else root/path
  expected=item['sha256'];data=None
  if path.is_file():
   actual=record(path)
   if actual['sha256']==expected:data=actual
  if data is None and expected in version_paths:
   actual_path=version_paths[expected];data=record(actual_path);historical.append({'receipt':context,'original_path':str(path),'archived_source':actual_path.name,**data});return
  require(data is not None,'unresolved changed/missing binding: '+str(path)+' in '+context)
  if 'bytes' in item:require(data['bytes']==item['bytes'],'bound byte count changed')
  if path.is_relative_to(root):
   rel=path.relative_to(root).as_posix()
   if rel.startswith(('build/','models/')):
    omissions[str(path)]={'path':str(path),**data,'reason':'Checksum-bound model or compiled executable; source/build receipts are retained, binary is not copied.'}
   else:sources.add(rel)
  elif path.is_relative_to(ref):
   if path.read_bytes()[:4]==b'\x7fELF':omissions[str(path)]={'path':str(path),**data,'reason':'Compiled executable; build command/source/hash retained.'}
   else:add(path)
  else:
   # Token projection sources were created outside reference; preserve bytes
   # beneath an explicit name and record the original path unchanged.
   same=next((name for name,blob in payload.items() if sha(blob)==expected),None)
   if same:historical.append({'receipt':context,'original_path':str(path),'archived_source':same,**data})
   else:add(path,'external-inputs/'+path.name)
 for directory in ['v4-token-final','v5-token-final','holdout-token-final','holdout-token-candidate-1','holdout-erase-candidate-audit']+[f'candidate-audit-{i}' for i in range(1,6)]:
  receipt=load(ref/directory/'receipt.json');require(receipt['status']=='complete' and receipt['returncode']==0 and receipt['bindings_unchanged'] is True,'token audit failed: '+directory)
  for item in receipt['bindings_before']+receipt['outputs']:binding(item,directory+'/receipt.json')
 for directory in ['v5-native-v2','holdout-v5-native-v2']:
  receipt=load(ref/directory/'receipt.json');require(receipt['status']=='completed' and receipt['sources_unchanged'] is True and receipt['model_forward_calls']==0 and receipt['summary']['pass'] is True,'native preflight incomplete')
  for item in receipt['bindings']+receipt['artifacts']:binding(item,directory+'/receipt.json')
  for phase in receipt['phases']:
   require(phase['returncode']==0,'preflight phase failed')
   binding(phase['stdout'],directory+'/receipt.json');binding(phase['stderr'],directory+'/receipt.json')
 failed=load(ref/'holdout-v5-native/receipt.json');require(failed['status']=='failed' and len(failed['phases'])==1 and failed['model_forward_calls']==0,'failed heldout receipt changed')
 for phase in failed['phases']:binding(phase['stdout'],'holdout-v5-native/receipt.json');binding(phase['stderr'],'holdout-v5-native/receipt.json')
 for name in ['independent-v5-audit.json','independent-v5-audit-final.json','independent-holdout-audit.json','independent-holdout-projection-audit.json']:
  receipt=load(ref/name);require(receipt['status']=='PASS','independent semantic gate failed')
  for item in receipt['bindings']:binding(item,name)
 integrity=load(ref/'integrity-audit.json');require(not integrity['remaining_blockers'],'readout integrity blockers')
 for item in integrity['audited_sources']:binding(item,'integrity-audit.json')
 dependency=load(ref/'makefile-test-dependency.json');require(dependency['status']=='pass' and dependency['verification']['rebuilt_cli_bytes_identical'],'clean build dependency gate failed')
 for item in [dependency['before'],dependency['after'],dependency['verification']['log'],dependency['verification']['readout_cli_before'],dependency['verification']['readout_cli_after']]:binding(item,'makefile-test-dependency.json')
 protocol=load(ref/'protocol.json');require(protocol['status']=='data_ready_training_not_started' and protocol['scientific_design_frozen'] and not protocol['execution_frozen'] and protocol['current_actions']['training_started'] is False,'protocol status changed')
 train=load(ref/'v5-native-v2/receipt.json')['summary'];held=load(ref/'holdout-v5-native-v2/receipt.json')['summary']
 require((train['examples'],train['decision_positions'],train['residual_positions'],train['chatml_comparisons'])==(76,52,1012,152),'training objective shape changed')
 require((held['examples'],held['review_pairs'],held['chatml_comparisons'])==(24,12,48),'heldout preflight shape changed')
 match=load(ref/'v4-v5-token-comparison.json');require(match['seven_features_and_after_return_count_equal_for_every_modified_pair'] and match['v5_all_seven_equal_pairs']==17 and match['v4_all_seven_equal_pairs']==5,'pair matching mismatch')
 tests=(ref/'tests.txt').read_text();require(re.search(r'(?:#|ℹ) tests 80\b',tests) and re.search(r'(?:#|ℹ) pass 80\b',tests) and re.search(r'(?:#|ℹ) fail 0\b',tests),'Node regression gate incomplete')
 for name in ['head','mlp','optimizer','weighting','joint','readout-extract','readout']:require('./build/test-'+name+'\n' in tests,'native test omitted')
 source_records={name:record(root/name) for name in sorted(sources)}
 # Source and evidence have all been validated before any archive is created.
 out.mkdir(parents=True)
 for name,data in payload.items():
  path=out/name;path.parent.mkdir(parents=True,exist_ok=True)
  with path.open('xb') as f:f.write(data)
 manifest={'schema_version':1,'status':'data_ready_training_not_started','parent_commit':protocol['parent_commit'],
  'evidence':{name:{'runtime_path':origins[name],'sha256':sha(data),'bytes':len(data)} for name,data in sorted(payload.items())},
  'source_files':source_records,'omitted_models_and_executables':list(omissions.values()),'historical_binding_resolution':historical,
  'verification':{'current_training_semantic_audit':'independent-v5-audit-final.json','native_model_forward_calls':0,'training_runs':0,'native_chatml_comparisons':200,'train_review_rows':52,'heldout_review_rows':24,'training_decision_targets':52,'training_residual_targets':1012,'modified_pairs_seven_features_and_return_matched':12,'heldout_pairs_seven_features_and_return_matched':12,'native_tests':7,'node_tests':80},
  'evidence_bytes':'Copied byte-for-byte; source paths and historical receipt bindings are preserved. Repository code/data remain in their normal locations with source hashes.',
  'reproduction':'reproduction.json contains literal structured commands for data rebuilding, semantic/native audits and the planned training/score invocation.'}
 with (out/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2);f.write('\n')
 for name,data in payload.items():require((out/name).read_bytes()==data,'post-copy byte mismatch')
 print(json.dumps({'files':len(payload)+1,'bytes':sum(len(v) for v in payload.values())+(out/'manifest.json').stat().st_size,'sources':len(source_records),'manifest':record(out/'manifest.json')}))
if __name__=='__main__':main()
