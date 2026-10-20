"""Authenticated Runpod HTTP worker. Logs and final weights stay on the pod."""
import http.server,os,json,threading,subprocess,time,urllib.request,traceback
from pathlib import Path
os.environ['HF_HUB_ENABLE_HF_TRANSFER']='0'
ROOT=Path('/workspace/jovovich-job');ROOT.mkdir(exist_ok=True)
STATE={'status':'starting'}
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        if self.headers.get('Authorization')!='Bearer '+os.environ['JOB_TOKEN']:
            self.send_error(403);return
        if self.path!='/retry' or STATE['status'] not in ('failed','completed'):
            self.send_error(409);return
        size=int(self.headers.get('Content-Length','0'))
        if size>500000:self.send_error(413);return
        update=json.loads(self.rfile.read(size))
        allowed={'train.py','review.py','requirements.txt','data/train.jsonl','data/validation.jsonl','data/test.jsonl'}
        if not set(update).issubset(allowed):self.send_error(400);return
        for name,content in update.items():Path(name).write_text(content)
        STATE.clear();STATE['status']='starting'
        threading.Thread(target=job,daemon=True).start()
        self.send_response(200);self.end_headers();self.wfile.write(b'accepted')
    def do_GET(self):
        if self.headers.get('Authorization')!='Bearer '+os.environ['JOB_TOKEN']:
            self.send_error(403);return
        if self.path=='/status':
            body=json.dumps(STATE).encode()
        elif self.path=='/log':
            p=ROOT/'job.log';body=p.read_bytes()[-24000:] if p.exists() else b''
        elif self.path=='/baseline':
            p=ROOT/'baseline.jsonl';body=p.read_bytes() if p.exists() else b''
        elif self.path=='/reviews':
            p=ROOT/'reviews.jsonl';body=p.read_bytes() if p.exists() else b''
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
def job():
    try:
        with (ROOT/'job.log').open('w',buffering=1) as log:
            commands=[['python','-m','pip','install','-r','requirements.txt']]
            if os.environ.get('RUN_MODE')!='eval':
                commands.append(['python','-u','train.py','--check-only'])
                if os.environ.get('BASELINE_COMPLETE_SHA256'):
                    import hashlib
                    assert hashlib.sha256((ROOT/'baseline.jsonl').read_bytes()).hexdigest()==os.environ['BASELINE_COMPLETE_SHA256']
                    assert hashlib.sha256(Path('data/validation.jsonl').read_bytes()).hexdigest()==os.environ['BASELINE_DATA_SHA256']
                    assert hashlib.sha256(Path('review.py').read_bytes()).hexdigest()==os.environ['BASELINE_REVIEW_SHA256']
                    baseline=[json.loads(s) for s in (ROOT/'baseline.jsonl').read_text().splitlines()]
                    cases=[json.loads(s) for s in Path('data/validation.jsonl').read_text().splitlines()]
                    assert [(r['id'],r['expected']) for r in baseline]==[(r['id'],r['expected']) for r in cases]
                else:
                    commands.append(['python','-u','review.py','--model','Qwen/Qwen2.5-Coder-1.5B-Instruct','--revision','2e1fd397ee46e1388853d2af2c993145b0f1098a','--cases','data/validation.jsonl'])
                commands.append(['python','-u','train.py','--epochs','3'])
            commands.append(['python','-u','review.py','--model',os.environ.get('REVIEW_MODEL','/workspace/jovovich-final'),'--cases','data/test.jsonl'])
            for cmd in commands:
                STATE.update(status='running',command=cmd)
                filename='baseline.jsonl' if 'data/validation.jsonl' in cmd else 'reviews.jsonl'
                output=log if 'review.py' not in cmd else (ROOT/filename).open('w',buffering=1)
                try:subprocess.run(cmd,stdout=output,stderr=log,check=True)
                finally:
                    if output is not log:output.close()
            STATE.update(status='completed')
    except Exception as e:STATE.update(status='failed',error=str(e))
def shutdown_watchdog():
    started=time.monotonic();finished=None
    while True:
        if STATE['status'] in ('completed','failed') and finished is None: finished=time.monotonic()
        if STATE['status'] not in ('completed','failed'): finished=None
        if time.monotonic()-started>5400 or (finished and time.monotonic()-finished>900):
            query='mutation { podStop(input:{podId:"'+os.environ['RUNPOD_POD_ID']+'"}) { id } }'
            req=urllib.request.Request('https://api.runpod.io/graphql',data=json.dumps({'query':query}).encode(),headers={'Authorization':'Bearer '+os.environ['RUNPOD_API_KEY'],'Content-Type':'application/json'})
            try: urllib.request.urlopen(req,timeout=30).read();return
            except Exception: time.sleep(30)
        time.sleep(10)
threading.Thread(target=shutdown_watchdog,daemon=True).start()
threading.Thread(target=job,daemon=True).start()
http.server.ThreadingHTTPServer(('0.0.0.0',8888),Handler).serve_forever()
