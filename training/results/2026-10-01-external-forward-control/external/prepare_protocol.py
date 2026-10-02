"""Bind a narrow external diagnostic after compilation, without running either model."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parent/'jovovich'
PIN = '680a036285273a3ff56032ec5d7f3352609eba4f'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            digest.update(chunk)
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=digest.hexdigest())


def main():
    pin = subprocess.check_output(['git','-C',str(HERE/'llama.cpp'),'rev-parse','HEAD'],text=True).strip()
    require(pin == PIN, 'reference commit changed')
    require(not subprocess.check_output(['git','-C',str(HERE/'llama.cpp'),'status','--porcelain'],text=True).strip(), 'reference tree is dirty')
    native_pin = subprocess.check_output(['git','-C',str(REPO/'deps/notorch'),'rev-parse','HEAD'],text=True).strip()
    require(native_pin == '7e246e13f9dbbb7e61312b7341fb94ce492bff71', 'native substrate pin changed')
    inputs = json.loads((HERE/'fixed-inputs.json').read_text())
    install = json.loads((HERE/'cmake-install-report.json').read_text())
    sources = [HERE/name for name in ('logit_io.h','dump_notorch.c','dump_llama.cpp','compare_logits.c',
        'CMakeLists.txt','prepare_inputs.py','prepare_protocol.py','fixed-inputs.json','cmake-install-report.json')]
    sources += [REPO/'deps/notorch'/name for name in ('notorch.c','notorch.h','gguf.c','gguf.h',
        'harness/runtime.c','harness/runtime.h','harness/arch_llama.c','harness/arch.h','harness/arch_models.h')]
    reference_keys=['include/llama.h','ggml/src/ggml-cpu/ggml-cpu.c','ggml/src/ggml-cpu/quants.c',
        'src/models/qwen2.cpp','src/llama-model.cpp','src/llama-context.cpp']
    sources += [HERE/'llama.cpp'/name for name in reference_keys]
    for case in inputs['cases']:
        sources += [Path(case[key]['path']) for key in ('ids','prompt')]
    binaries = {name:record(HERE/path) for name,path in [('notorch','dump-notorch'),('llama','build/dump-llama'),('comparison','compare-logits')]}
    model = record(REPO/'models/base-qwen.gguf')
    require(model['sha256']=='e1a77721fa97d412f121878223eec81fb4ae6f271e18f922d746711f67b344d1' and model['bytes']==675710848, 'base model changed')
    flags = {str(path.relative_to(HERE)):record(path) for path in (HERE/'build').rglob('flags.make')}
    plan = dict(schema_version=1, status='prepared_no_model_forwards', execution_authorized=False,
        scientific_scope='External independent forward comparison on one preselected original-base pair; no v5 checkpoint choice or behavioral score is changed.',
        model=model, reference_commit=PIN, notorch_pin=native_pin,
        fixed_inputs=record(HERE/'fixed-inputs.json'), cases=inputs['cases'], captures_per_engine=4, model_forward_calls=0,
        sources=[record(p) for p in sources], binaries=binaries,
        compiler={name:subprocess.check_output([name,'--version'],text=True).splitlines()[0] for name in ('cc','c++')},
        cmake_dependency=[dict(name=item['metadata']['name'],version=item['metadata']['version'],
            wheel_hashes=item['download_info']['archive_info']['hashes']) for item in install['install']],
        build=dict(priority_nice=15,parallel_workers=1,cmake_cache=record(HERE/'build/CMakeCache.txt'),
            cmake_flags=flags, logs=[record(HERE/name) for name in ('configure.stdout','configure.stderr','configure-v2.stdout','configure-v2.stderr',
                'build-notorch.stdout','build-notorch.stderr','build-llama.stdout','build-llama.stderr','build-compare.stdout','build-compare.stderr')],
            native_compile_flags=['-O2','-Wall','-Wextra','-std=gnu11','-march=native','-lm','-pthread'],
            reference_configuration=['Release','BUILD_SHARED_LIBS=OFF','GGML_CPU_REPACK=OFF','GGML_OPENMP=OFF','GGML_BLAS=OFF','GGML_LLAMAFILE=OFF','GGML_NATIVE=ON']),
        execution=dict(order='Serial, concern then clean, native and reference per case; only after root explicitly authorizes forwards.',
            environment={'NT_NO_I8':'1','NT_QMV_THREADS':'1','NT_ATTN_THREADS':'1','NT_SIMD_THREADS':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'},
            environment_cleanup='Remove inherited NT_* before assigning the listed native settings.',
            reference=dict(cpu_only=True,threads=1,kv_dtype='F32',flash_attention=False,repacking=False,sampler=None),
            prefill_chunk=32,context=2048,tokenization='Use archived IDs directly in both engines; no engine template, tokenizer or BOS insertion.',
            positions='Last assistant-header token at 443, then consume all three exact prefix IDs and capture position446.',
            required_receipts='Before and after: exact model/source/binary/input hashes. Preserve argv, exit status, logs, resources, all created binary dumps and metrics, including failed attempts.'),
        format=dict(name='JVL2',byte_order='little-endian',dtype='IEEE754 float32',header_u32=['magic0x324c564a','version2','dtype1','vocabulary151936','capture_rows2','input_ids447'],
            input_tokens='447 uint32 IDs in exact forward order',row_layout='uint32 prefix_length followed by 151936 float32 logits in vocabulary-ID order',
            expected_bytes_per_dump=24+447*4+2*(4+151936*4), expected_dump_count=4, expected_total_dump_bytes=4*(24+447*4+2*(4+151936*4))),
        metrics=['max absolute logit difference and its token ID','relative L2 using reference norm','RMSE','mean absolute difference','bitwise-different float count',
            'full-vocabulary argmax','top1 minus top2 margins for each engine','top10 IDs/logits for each engine','concern66582 minus clean788 logit margin'],
        q8_interpretation=dict(notorch='NT_NO_I8=1 keeps float activations for quantized weight operations.',
            reference='ggml CPU Q8_0 traits specify vec_dot_q8_0_q8_0 and vec_dot_type Q8_0; activation quantization introduces an expected arithmetic difference.',
            conclusion='Original Q8 comparisons measure actual engine disagreement. A discrepancy alone is not evidence of a notorch forward defect.',
            alignment_trigger=dict(status='proposed_for_independent_review_before_any_forward', any_of=['argmax differs at any capture','concern-minus-clean signs differ at prefix447','relative_l2 > 1e-4','max_abs > 1e-3 * (1 + reference_max_abs)'],
                purpose='Screening threshold to request a separately authorized arithmetic alignment control, not a pass/fail correctness threshold.')),
        optional_alignment_control=dict(execute=False,requires_root_authorization=True,
            method='Use native llama-quantize F32 or a native GGUF converter on this exact Q8 file. Validate each expanded tensor against an independent notorch Q8 dequantization element-for-element before any aligned forward.',
            weight_contract='Every tensor name, shape and numeric value must agree exactly with dequantization of the original; preserve architecture/tokenizer/position/norm metadata and tie/output semantics; explicitly enumerate converter bookkeeping changes such as general.file_type and quantization-version metadata. Bind full per-tensor hashes and model byte extent. No fine-tuning or alternate source weights.',
            comparisons='Native Q8-float-activation versus native expanded-F32 isolates packed-kernel arithmetic; native expanded-F32 versus reference same-F32 isolates shared-weight forward differences. Keep both separately from original-Q8 comparison.',
            decision='Review original-Q8 measurements and all-tensor conversion audit before deciding whether to execute alignment; no silent fallback.'),
        portable_evidence='Archive only sources, fixed inputs, compact compiler/configuration receipts, logs, plan, binary logit dumps and metric receipts. Exclude full llama checkout, build tree, venv and model weights.')
    with (HERE/'protocol.json').open('x') as output:
        output.write(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(dict(protocol=record(HERE/'protocol.json'),model_forwards=0,planned_logit_bytes=plan['format']['expected_total_dump_bytes'])))


if __name__=='__main__':
    main()
