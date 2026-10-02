"""Check the native metric reader on constant synthetic arrays, without a model."""
from array import array
import hashlib
import json
from pathlib import Path
import struct
import subprocess

HERE=Path(__file__).resolve().parent


def require(condition,message):
    if not condition:
        raise ValueError(message)


def record(path):
    data=Path(path).read_bytes()
    return dict(path=str(Path(path).resolve()),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


def main():
    out=HERE/'synthetic-check'
    out.mkdir(exist_ok=False)
    ids=[int(x) for x in (HERE/'concern.ids.txt').read_text().split()]
    for name,constants in [('native.dump',[1.0,3.0]),('reference.dump',[2.0,3.0])]:
        with (out/name).open('xb') as stream:
            stream.write(struct.pack('<6I',0x324c564a,2,1,151936,2,447))
            stream.write(struct.pack('<447I',*ids))
            for position,value in zip([444,447],constants):
                stream.write(struct.pack('<I',position))
                array('f',[value]*151936).tofile(stream)
    command=[str(HERE/'compare-logits'),str(out/'native.dump'),str(out/'reference.dump')]
    completed=subprocess.run(command,capture_output=True,text=True)
    (out/'metrics.jsonl').write_text(completed.stdout)
    (out/'stderr.txt').write_text(completed.stderr)
    require(completed.returncode==0,'native comparison failed')
    rows=[json.loads(s) for s in completed.stdout.splitlines()]
    require(len(rows)==2,'wrong comparison coverage')
    for row,error,relative,count in zip(rows,[1,0],[0.5,0],[151936,0]):
        require(row['max_abs']==row['rmse']==row['mean_abs']==error,'constant-array error mismatch')
        require(row['relative_l2']==relative and row['different_float32_values']==count,'relative/count mismatch')
        require(row['argmax_agree'] is True and row['notorch_argmax']==row['llama_argmax']==0,'tie policy mismatch')
        require(row['notorch_top_margin']==row['llama_top_margin']==0,'top margin mismatch')
    bad=bytearray((out/'reference.dump').read_bytes())
    struct.pack_into('<I',bad,24,(ids[0]+1)%151936)
    (out/'different-ids.dump').write_bytes(bad)
    rejected=subprocess.run([str(HERE/'compare-logits'),str(out/'native.dump'),str(out/'different-ids.dump')],capture_output=True,text=True)
    require(rejected.returncode!=0 and 'different input token IDs' in rejected.stderr,'mismatched input IDs accepted')
    result=dict(passed=True,model_forward_calls=0,synthetic_only=True,
        helper=record(__file__),comparator=record(HERE/'compare-logits'),
        assertions=['constant relative L2 0.5','constant max/mean/RMS error1','identical row zero error','stable argmax tie IDs','mismatched token IDs refused'],
        metrics=record(out/'metrics.jsonl'),input_bindings=[record(out/name) for name in ('native.dump','reference.dump','different-ids.dump')],
        rejection=dict(exit_code=rejected.returncode,stderr=rejected.stderr))
    with (HERE/'synthetic-check.json').open('x') as stream:
        stream.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,model_forward_calls=0,synthetic_rows=2,id_mismatch_rejected=True)))


if __name__=='__main__':
    main()
