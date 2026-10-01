"""Byte/metadata orchestration; all numeric tensor comparison runs in native C."""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import mmap
from pathlib import Path
import struct
import subprocess

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent/'jovovich'
PARSER=REPO/'training/results/2026-09-29-convergence/check_convergence_export.py'
spec=importlib.util.spec_from_file_location('existing_byte_parser',PARSER)
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
require=audit.require


def record(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):
            h.update(block)
    return dict(path=str(Path(path).resolve()),bytes=Path(path).stat().st_size,sha256=h.hexdigest())


def metadata(data):
    pos=0
    def take(size):
        nonlocal pos
        require(0<=size<=len(data)-pos,'truncated metadata')
        value=data[pos:pos+size];pos+=size;return value
    def integer(fmt):
        return struct.unpack('<'+fmt,take(struct.calcsize('<'+fmt)))[0]
    def string():
        return take(integer('Q'))
    def skip(kind):
        sizes={0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}
        if kind in sizes:
            take(sizes[kind])
        elif kind==8:
            string()
        elif kind==9:
            item,count=integer('I'),integer('Q')
            require(item!=9,'nested metadata arrays unsupported')
            for _ in range(count):
                skip(item)
        else:
            raise ValueError('unknown metadata value type')
    require(take(4)==b'GGUF' and integer('I')==3,'expected GGUFv3')
    tensors,count=integer('Q'),integer('Q')
    values={}
    for _ in range(count):
        key=string().decode('utf-8')
        require(key not in values,'duplicate metadata key')
        begin=pos
        skip(integer('I'))
        values[key]=data[begin:pos]
    return values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--converted',type=Path,required=True)
    parser.add_argument('--native-verifier',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    result=dict(status='started',model_forwards=0,numeric_comparison='notorch gguf_dequant_row in standalone C; Python only parses/hashes bytes',
        base=record(args.base),converted=record(args.converted),verifier=record(args.native_verifier),script=record(__file__),parser=record(PARSER))
    require(result['base']['sha256']=='e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1','wrong original model')
    try:
        with ExitStack() as stack:
            def mapped(path):
                stream=stack.enter_context(path.open('rb'))
                return stack.enter_context(mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ))
            base,converted=mapped(args.base),mapped(args.converted)
            original,expanded=audit.parse_gguf(base),audit.parse_gguf(converted)
            bm,cm=metadata(base),metadata(converted)
            changed=[]
            # Exact, documented bookkeeping rewrites performed by this pinned producer.
            expected_file_type=struct.pack('<II',4,0)
            expected_quant_version=struct.pack('<II',4,2)
            require(cm.get('general.file_type')==expected_file_type,'converted general.file_type is not ALL_F32')
            require(cm.get('general.quantization_version')==expected_quant_version,'unexpected converter quantization version')
            allowed={'general.file_type','general.quantization_version'}
            for key in ('split.no','split.count','split.tensors.count'):
                require(key not in bm and key not in cm,'unsharded exact source must not gain or lose split metadata')
            require(set(cm)-set(bm)<=allowed and set(bm)-set(cm)<=allowed,'metadata keys were added/removed')
            for key in sorted(set(bm)|set(cm)):
                same=bm.get(key)==cm.get(key)
                require(same or key in allowed,'model/tokenizer metadata changed: '+key)
                if not same:
                    changed.append(dict(key=key,original_hex=bm[key].hex() if key in bm else None,converted_hex=cm[key].hex()))
            original_by_name={item['name']:item for item in original['tensors']}
            actual_by_name={item['name']:item for item in expanded['tensors']}
            require(len(original_by_name)==len(actual_by_name)==291 and set(original_by_name)==set(actual_by_name),'tensor identities changed')
            payloads=[];cursor=0
            for tensor in expanded['tensors']:
                original_tensor=original_by_name[tensor['name']]
                require(tensor['shape']==original_tensor['shape'] and tensor['type']==0,'tensor shape/type mismatch')
                require(tensor['offset']==cursor,'noncontiguous F32 payload layout')
                start=expanded['data_offset']+tensor['offset']
                payloads.append(dict(name=tensor['name'],shape=tensor['shape'],bytes=tensor['bytes'],sha256=audit.digest(converted,start,tensor['bytes'])))
                cursor=audit.align32(cursor+tensor['bytes'])
            require(len(converted)==expanded['data_offset']+cursor,'F32 byte extent differs from exact directory payload')
            require(expanded['data_offset']==5947776 and len(converted)==2526617472,'fixed source expansion extent changed')
            result.update(metadata_keys_checked=len(set(bm)|set(cm)),metadata_changes=changed,semantic_metadata_exact=True,
                expected_byte_extent=expanded['data_offset']+cursor,tensors=payloads,tensor_reordering_allowed_by_name=True)
        command=[str(args.native_verifier.resolve()),str(args.base.resolve()),str(args.converted.resolve())]
        out_path,err_path=args.output_dir/'native-values.jsonl',args.output_dir/'native-values.stderr'
        result['native_command']=command
        with out_path.open('x') as out,err_path.open('x') as err:
            process=subprocess.run(command,stdout=out,stderr=err)
        result['native_exit_code']=process.returncode
        require(process.returncode==0,'native every-element comparison failed')
        lines=out_path.read_text().splitlines()
        rows=[json.loads(line) for line in lines]
        require(len(rows)==291 and {row['name'] for row in rows}==set(original_by_name),'incomplete native tensor coverage')
        require(all(row.get('exact_float32_bytes') is True and row.get('all_finite') is True for row in rows),'native tensor mismatch')
        require(record(args.base)==result['base'] and record(args.converted)==result['converted'],'model changed during validation')
        require(record(args.native_verifier)==result['verifier'] and record(__file__)==result['script'] and record(PARSER)==result['parser'],'validator source/binary changed')
        result.update(status='completed',every_tensor_exact=True,all_finite=True)
    except BaseException as error:
        result.update(status='failed',failure_type=type(error).__name__,failure=str(error))
    finally:
        result['artifacts']=[record(path) for path in sorted(args.output_dir.iterdir()) if path.is_file()]
        with (args.output_dir/'validation.json').open('x') as out:
            out.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],receipt=str(args.output_dir/'validation.json'))))
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
