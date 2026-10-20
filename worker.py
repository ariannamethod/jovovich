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
        allowed={'train.py','review.py','requirements.txt','data/train.jsonl','data/eval.jsonl'}
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
        elif self.path=='/reviews':
            p=ROOT/'reviews.jsonl';body=p.read_bytes() if p.exists() else b''
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
def job():
    try:
        with (ROOT/'job.log').open('w',buffering=1) as log:
            for cmd in [['python','-m','pip','install','-r','requirements.txt'],['python','-u','train.py','--epochs','6'],['python','-u','review.py','--model','/workspace/jovovich-final','--cases','data/eval.jsonl']]:
                STATE.update(status='running',command=cmd[2] if len(cmd)>2 else cmd[-1])
                output=log if 'review.py' not in cmd else (ROOT/'reviews.jsonl').open('w',buffering=1)
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
