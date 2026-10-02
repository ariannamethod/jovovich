"""Bind optional compiled F32 alignment tools; perform no conversion or forward."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
REPO=PARENT.parent/'jovovich'


def require(condition,message):
    if not condition:
        raise ValueError(message)


def record(path):
    path=Path(path)
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            digest.update(chunk)
    return dict(path=str(path.resolve()),bytes=path.stat().st_size,sha256=digest.hexdigest())


def main():
    protocol=json.loads((PARENT/'protocol.json').read_text())
    execution=json.loads((PARENT/'execution-plan-v2.json').read_text())
    # Do not reconfigure or mutate any existing reference build artifacts.
    frozen=[*execution['bindings'],protocol['build']['cmake_cache'],*protocol['build']['cmake_flags'].values()]
    for item in frozen:
        require(record(item['path'])==item,'original-Q8 frozen binding changed')
    libraries=[PARENT/'build'/name for name in ('llama.cpp/src/libllama.a','llama.cpp/ggml/src/libggml.a',
        'llama.cpp/ggml/src/libggml-cpu.a','llama.cpp/ggml/src/libggml-base.a')]
    sources=[HERE/name for name in ('convert_f32.cpp','verify_tensor_values.c','verify_alignment.py','compare_alignment_logits.c','prepare_alignment_plan.py')]
    sources += [PARENT/'logit_io.h',PARENT/'llama.cpp/src/llama-quant.cpp',PARENT/'llama.cpp/include/llama.h',
        REPO/'deps/notorch/gguf.c',REPO/'deps/notorch/gguf.h',REPO/'training/results/2026-09-29-convergence/check_convergence_export.py']
    binaries={name:record(HERE/name) for name in ('convert-f32','verify-tensor-values','compare-alignment-logits')}
    output=HERE/'run-1'
    converted=output/'original-base-expanded-f32.gguf'
    require(not output.exists(),'alignment output path already exists')
    plan=dict(schema_version=1,status='proposed_not_authorized',conversion_executed=False,model_forward_calls=0,
        original_protocol=record(PARENT/'protocol.json'),original_execution=record(PARENT/'execution-plan-v2.json'),
        original_frozen_bindings_rechecked=len(frozen),original_frozen_files_unchanged=True,
        scope='Arithmetic alignment of the same original Q8 tensor values; no alternate model, training, selection or prompt choice.',
        trigger='Only a separate root decision after completed original-Q8 measurements and independent source review may authorize conversion/forwards.',
        original_model=protocol['model'],fixed_inputs=protocol['fixed_inputs'],cases=protocol['cases'],
        sources=[record(path) for path in sources],binaries=binaries,linked_reference_libraries=[record(path) for path in libraries],
        compiler={name:subprocess.check_output([name,'--version'],text=True).splitlines()[0] for name in ('cc','c++')},
        build=dict(location=str(HERE),serial=True,nice=15,
            converter_flags=['-O2','-std=c++17','-ldl','-lm'],verifier_flags=['-O2','-Wall','-Wextra','-std=gnu11','-lm'],
            reference_build_reconfigured=False,logs=[record(HERE/name) for name in ('build-converter.stdout','build-converter.stderr',
            'build-verifier.stdout','build-verifier.stderr','build-comparison.stdout','build-comparison.stderr')]),
        converter=dict(producer='Pinned llama.cpp llama_model_quantize, using ggml dequantization',threads=1,ftype='ALL_F32',
            allow_requantize=True,pure=True,output_tensor_type='F32',token_embedding_type='F32',maximum_buffer_bytes=67108864,
            output_creation='O_EXCL reservation; producer may rewrite only its newly created file; partial file retained on error.',
            expected_stored_elements=630167424,expected_tensors=291,expected_byte_extent=2526617472,
            expected_metadata_changes={'general.file_type':{'original_u32':7,'converted_u32':0}},
            unchanged_quantization_version=2,no_split_metadata=True),
        independent_validation=dict(numeric='Every value via notorch gguf_dequant_row, independent of producer ggml; require bit-exact F32 and finite values.',
            coverage='All291 original names, shapes and630167424 stored values; physical tensor order may change, compare by exact name.',
            metadata='Independent standard-library byte parsing compares every typed metadata value, including all tokenizer arrays, RoPE/norm parameters and output/tie metadata. Only documented file_type rewrite is expected.',
            layout='All converted payload types F32; directory offsets contiguous/aligned; full file length exactly2526617472 with data offset5947776. Hash every converted tensor payload.',
            validation_gates='Require completed native exit0 with291 exact/finite tensor rows, all metadata/layout checks, and unchanged pre/post base/converted/source/binary hashes before any aligned forward.'),
        proposed_commands=dict(convert=['nice','-n','15',binaries['convert-f32']['path'],protocol['model']['path'],str(converted)],
            verify=['python3','-E',str(HERE/'verify_alignment.py'),'--base',protocol['model']['path'],'--converted',str(converted),
                '--native-verifier',binaries['verify-tensor-values']['path'],'--output-dir',str(output/'validation')]),
        forward_followup=dict(execute=False,requires_converted_model_hash_and_fresh_execution_plan=True,
            reused_harness_binaries=protocol['binaries'],same_ID_files_and_capture_positions=True,
            new_forward_processes=4,threads=1,serial=True,decoding=None,
            comparisons=[{'first':'prior notorch original-Q8 dump','second':'new notorch expanded-F32 dump','purpose':'isolate native packed-weight arithmetic'},
                         {'first':'new notorch expanded-F32 dump','second':'new llama.cpp same expanded-F32 dump','purpose':'independent forward arithmetic with identical fully verified F32 weights'}],
            comparator=binaries['compare-alignment-logits'],field_labels='first/second; second defines the relative-L2 denominator, without incorrectly naming two native arms as different engines.'),
        interpretation='Do not declare a forward defect from original-Q8 disagreement or from an arbitrary F32 aggregate tolerance alone. Preserve exact vector differences, ranks and margins; use verified conversion plus matched arithmetic to localize any discrepancy.',
        persistence='Converted model is a temporary weight artifact, excluded from public code/evidence archives; retain receipts/per-tensor hashes and bounded logit dumps separately.')
    with (HERE/'proposed-plan.json').open('x') as stream:
        stream.write(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(dict(plan=record(HERE/'proposed-plan.json'),original_frozen_files_unchanged=True,model_forwards=0,conversions=0)))


if __name__=='__main__':
    main()
