"""Authenticated Runpod HTTP worker. Logs and final weights stay on the pod."""
import http.server,os,json,threading,subprocess,time,urllib.request,shutil,hashlib
from pathlib import Path
os.environ['HF_HUB_ENABLE_HF_TRANSFER']='0'
ROOT=Path('/workspace/jovovich-job');ROOT.mkdir(exist_ok=True)
STATE={'status':'starting'}
OVERRIDE_COMMANDS=None
MAX_REQUEST_BYTES=8*1024*1024
def update_state(**values):
    STATE.update(values)
    target=ROOT/'state.json'
    temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(STATE))
    temporary.replace(target)
    print('JOVOVICH_STATE '+json.dumps(STATE),flush=True)
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        global OVERRIDE_COMMANDS
        if self.headers.get('Authorization')!='Bearer '+os.environ['JOB_TOKEN']:
            self.send_error(403);return
        if self.path=='/run':
            if STATE['status'] not in ('completed','failed'):self.send_error(409);return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=MAX_REQUEST_BYTES:self.send_error(413);return
            request=json.loads(self.rfile.read(size))
            commands=request.get('commands',[])
            allowed={'batch_review.py','distill.py','train.py','review.py','evaluate.py'}
            if not commands or any(not isinstance(c,list) or len(c)<3 or c[:2]!=['python','-u'] or c[2] not in allowed or any(not isinstance(a,str) for a in c) for c in commands):
                self.send_error(400);return
            files=request.get('files',{})
            if not set(files).issubset(allowed|{'model_config.py','fixture_quality.py','data/fixture_quarantine.json','data/train_distilled.jsonl','data/train.jsonl','data/validation.jsonl','data/test.jsonl','data/acceptance.jsonl'}):self.send_error(400);return
            for name,content in files.items():Path(name).write_text(content)
            OVERRIDE_COMMANDS=commands
            STATE.clear();STATE['status']='starting'
            threading.Thread(target=job,daemon=True).start()
            self.send_response(200);self.end_headers();self.wfile.write(b'accepted');return
        if self.path=='/approve-data':
            if STATE['status']!='awaiting_data_review':self.send_error(409);return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=256:self.send_error(413);return
            approval=json.loads(self.rfile.read(size))
            current=hashlib.sha256(Path('data/train_distilled.jsonl').read_bytes()).hexdigest()
            if approval.get('sha256')!=current:self.send_error(409);return
            os.environ['APPROVED_DATA_SHA256']=current
            self.send_response(200);self.end_headers();self.wfile.write(b'approved');return
        if self.path!='/retry' or STATE['status'] not in ('failed','completed'):
            self.send_error(409);return
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<=MAX_REQUEST_BYTES:self.send_error(413);return
        update=json.loads(self.rfile.read(size))
        allowed={'distill.py','train.py','review.py','model_config.py','fixture_quality.py','data/fixture_quarantine.json','requirements.txt','data/train.jsonl','data/validation.jsonl','data/test.jsonl','data/acceptance.jsonl'}
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
        elif self.path=='/model':
            if STATE['status']!='completed':self.send_error(409);return
            model=Path('/workspace/jovovich-final')
            files=[]
            for p in model.iterdir():
                if p.is_file() and not p.is_symlink():
                    with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
                    files.append({'name':p.name,'bytes':p.stat().st_size,'sha256':digest})
            body=json.dumps(files).encode()
        elif self.path.startswith('/model/'):
            if STATE['status']!='completed':self.send_error(409);return
            name=self.path[len('/model/'):]
            if not name or name!=Path(name).name or name in ('.','..'):self.send_error(400);return
            p=Path('/workspace/jovovich-final')/name
            if not p.is_file() or p.is_symlink():self.send_error(404);return
            self.send_response(200);self.send_header('Content-Length',str(p.stat().st_size));self.end_headers()
            with p.open('rb') as f:shutil.copyfileobj(f,self.wfile)
            return
        elif self.path=='/baseline':
            p=ROOT/'baseline.jsonl';body=p.read_bytes() if p.exists() else b''
        elif self.path=='/reviews':
            p=ROOT/'reviews.jsonl';body=p.read_bytes() if p.exists() else b''
        elif self.path=='/training-data':
            p=ROOT/'data/train_distilled.jsonl';body=p.read_bytes() if p.exists() else b''
        elif self.path.startswith('/artifact/'):
            name=self.path[len('/artifact/'):]
            if name!=Path(name).name or Path(name).suffix not in ('.json','.jsonl','.log'):
                self.send_error(400);return
            p=ROOT/name
            if not p.is_file() or p.is_symlink():self.send_error(404);return
            body=p.read_bytes()
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
def job():
    try:
        with (ROOT/'job.log').open('w',buffering=1) as log:
            commands=[['python','-m','pip','install','-r','requirements.txt']]
            if os.environ.get('RUN_MODE')!='eval':
                data_args=[]
                if os.environ.get('TEACHER_MODEL'):
                    if os.environ.get('TEACHER_DATA_SHA256'):
                        if hashlib.sha256(Path('data/train_distilled.jsonl').read_bytes()).hexdigest()!=os.environ['TEACHER_DATA_SHA256']:
                            raise ValueError('Approved training data checksum mismatch')
                    else:
                        commands.append(['python','-m','pip','install','vllm==0.32.0'])
                        commands.append(['python','-u','distill.py','--model',os.environ['TEACHER_MODEL'],
                                         '--revision',os.environ['TEACHER_REVISION']])
                    data_args=['--data','data/train_distilled.jsonl']
                commands.append(['python','-u','train.py','--check-only'] + data_args)
                if os.environ.get('SKIP_BASELINE') == '1':
                    pass
                elif os.environ.get('BASELINE_COMPLETE_SHA256'):
                    assert hashlib.sha256((ROOT/'baseline.jsonl').read_bytes()).hexdigest()==os.environ['BASELINE_COMPLETE_SHA256']
                    assert hashlib.sha256(Path('data/validation.jsonl').read_bytes()).hexdigest()==os.environ['BASELINE_DATA_SHA256']
                    assert hashlib.sha256(Path('review.py').read_bytes()).hexdigest()==os.environ['BASELINE_REVIEW_SHA256']
                    baseline=[json.loads(s) for s in (ROOT/'baseline.jsonl').read_text().splitlines()]
                    cases=[json.loads(s) for s in Path('data/validation.jsonl').read_text().splitlines()]
                    assert [(r['id'],r['expected']) for r in baseline]==[(r['id'],r['expected']) for r in cases]
                else:
                    from model_config import MODEL, REVISION
                    commands.append(['python','-u','review.py','--model',MODEL,'--revision',REVISION,'--cases','data/validation.jsonl'])
                commands.append(['python','-u','train.py','--epochs','3'] + data_args)
            review_command=['python','-u','review.py','--model',os.environ.get('REVIEW_MODEL','/workspace/jovovich-final'),'--cases','data/test.jsonl']
            if Path('data/acceptance.jsonl').exists():
                review_command.append('data/acceptance.jsonl')
            if os.environ.get('REVIEW_REVISION'):
                review_command += ['--revision',os.environ['REVIEW_REVISION']]
            commands.append(review_command)
            if OVERRIDE_COMMANDS is not None:
                commands=OVERRIDE_COMMANDS
            elif os.environ.get('JOB_COMMANDS'):
                commands=json.loads(os.environ['JOB_COMMANDS'])
            for cmd in commands:
                if '--check-only' in cmd and os.environ.get('TEACHER_REVIEW_REQUIRED')=='1':
                    digest=hashlib.sha256(Path('data/train_distilled.jsonl').read_bytes()).hexdigest()
                    update_state(status='awaiting_data_review',training_data_sha256=digest)
                    while os.environ.get('APPROVED_DATA_SHA256')!=digest:
                        time.sleep(1)
                update_state(status='running',command=cmd)
                filename='baseline.jsonl' if 'data/validation.jsonl' in cmd else 'reviews.jsonl'
                output=log if 'review.py' not in cmd else (ROOT/filename).open('w',buffering=1)
                try:
                    if 'review.py' in cmd:
                        process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=log,text=True,bufsize=1)
                        for line in process.stdout:
                            output.write(line);output.flush()
                            print('JOVOVICH_REVIEW '+line.rstrip(),flush=True)
                    else:
                        process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
                        for line in process.stdout:
                            log.write(line);log.flush()
                            print(line.rstrip(),flush=True)
                    if process.wait():
                        raise subprocess.CalledProcessError(process.returncode,cmd)
                finally:
                    if output is not log:output.close()
            update_state(status='completed')
    except Exception as e:
        print((ROOT/'job.log').read_text()[-6000:],flush=True)
        update_state(status='failed',error=str(e))
def shutdown_watchdog():
    started=time.monotonic();finished=None
    deadline=float(os.environ.get('JOB_DEADLINE_UNIX',time.time()+5400))
    while True:
        if STATE['status'] in ('completed','failed') and finished is None: finished=time.monotonic()
        if STATE['status'] not in ('completed','failed'): finished=None
        if time.time()>=deadline or time.monotonic()-started>5400 or (finished and time.monotonic()-finished>900):
            query='mutation { podStop(input:{podId:"'+os.environ['RUNPOD_POD_ID']+'"}) { id } }'
            req=urllib.request.Request('https://api.runpod.io/graphql',data=json.dumps({'query':query}).encode(),headers={'Authorization':'Bearer '+os.environ['RUNPOD_API_KEY'],'Content-Type':'application/json'})
            try: urllib.request.urlopen(req,timeout=30).read();return
            except Exception: time.sleep(30)
        time.sleep(10)
threading.Thread(target=shutdown_watchdog,daemon=True).start()
if os.environ.get('RUN_MODE')=='serve':
    STATE.update(json.loads((ROOT/'state.json').read_text()))
else:
    threading.Thread(target=job,daemon=True).start()
http.server.ThreadingHTTPServer(('0.0.0.0',8888),Handler).serve_forever()
