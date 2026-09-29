import hashlib,json,os,resource,subprocess,time
from pathlib import Path
root=Path.cwd();os.chdir(root)
prefix='models/verdict-balance'
assert hashlib.sha256(Path('training/train_mlp.c').read_bytes()).hexdigest()=='97f8cab893ebdc6d977ffa7f1d30a070d31d8171aefdca4b7442d3f39bdb42af'
command=['build/jovovich-train-mlp','models/base-qwen.gguf',prefix+'.bin',prefix,'12','0.001','48','4','verdict',prefix+'.pairs']
env=dict(os.environ,NT_QMV_THREADS='4',NT_ATTN_THREADS='4',NT_SIMD_THREADS='4')
receipt=dict(source_sha256=hashlib.sha256(Path('training/train_mlp.c').read_bytes()).hexdigest(),binary_sha256=hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),dataset_binary_sha256=hashlib.sha256(Path(prefix+'.bin').read_bytes()).hexdigest(),pair_map_sha256=hashlib.sha256(Path(prefix+'.pairs').read_bytes()).hexdigest())
Path(prefix+'-training-source.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(dict(phase='training',command=command,**receipt)),flush=True)
with open(prefix+'-metrics.jsonl','x') as out,open(prefix+'-train.stderr','x') as err:
 started=time.monotonic();result=subprocess.run(command,env=env,stdout=out,stderr=err)
usage=resource.getrusage(resource.RUSAGE_CHILDREN)
record=dict(command=command,objective='verdict',elapsed_seconds=time.monotonic()-started,peak_rss_kib=usage.ru_maxrss,user_seconds=usage.ru_utime,system_seconds=usage.ru_stime,exit_code=result.returncode)
Path(prefix+'-resource.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(dict(phase='complete',**record)),flush=True)
raise SystemExit(result.returncode)
