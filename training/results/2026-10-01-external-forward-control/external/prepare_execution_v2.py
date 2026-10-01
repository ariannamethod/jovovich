"""Freeze commands and receipts separately from the immutable scientific protocol."""
import importlib.util
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('external_controller',HERE/'run_external_v2.py')
controller=importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
record,save,require=controller.record,controller.save,controller.require


def main():
    protocol_path=HERE/'protocol.json'
    protocol=json.loads(protocol_path.read_text())
    require(record(protocol_path)['sha256']=='de41682bc67a36aeb550491c238de864af6e93f6295accbc9af8bb9d77ed53c7','scientific protocol changed')
    output=HERE/'q8-control-1'
    require(not output.exists(),'fresh output path already exists')
    nice=shutil.which('nice')
    require(nice is not None,'nice executable missing')
    bindings=[protocol['model'],*protocol['sources'],*protocol['binaries'].values(),record(protocol_path),record(HERE/'run_external_v2.py'),record(__file__),record(nice)]
    # De-duplicate only exact paths; divergent records for one path are refused.
    unique={}
    for item in bindings:
        require(item['path'] not in unique or unique[item['path']]==item,'inconsistent input binding')
        unique[item['path']]=item
    bindings=list(unique.values())
    controller.verify(bindings)
    phases=[]
    for label,case in zip(['concern','clean'],protocol['cases']):
        require(case['id']=='allocation-null-guard-deletion-'+label,'fixed pair order changed')
        for engine in ['notorch','llama']:
            name=label+'-'+engine
            dump=output/(name+'.dump')
            phases.append(dict(name=name,kind='model_forward',ids=case['ids'],command=[nice,'-n','15',protocol['binaries'][engine]['path'],protocol['model']['path'],case['ids']['path'],str(dump)],
                stdout=str(output/(name+'.stdout.jsonl')),stderr=str(output/(name+'.stderr')),outputs=[str(dump)]))
        name=label+'-comparison'
        phases.append(dict(name=name,kind='metric_comparison',command=[nice,'-n','15',protocol['binaries']['comparison']['path'],str(output/(label+'-notorch.dump')),str(output/(label+'-llama.dump'))],
            stdout=str(output/(name+'.jsonl')),stderr=str(output/(name+'.stderr')),outputs=[]))
    plan=dict(schema_version=1,status='ready_requires_root_execution_decision',protocol=record(protocol_path),controller=record(HERE/'run_external_v2.py'),
        working_directory=str(HERE),output_directory=str(output),bindings=bindings,
        environment=protocol['execution']['environment'],environment_cleanup='All inherited NT_* removed before fixed overrides.',
        phases=phases,model_forward_processes=4,metric_processes=2,
        screening_sign_rule='Use exact three-way sign on unrounded stored concern-minus-clean margins: negative=-1, exactzero=0, positive=1. An alignment trigger is not a forward correctness verdict.',
        execution_decision='Preparation only. Root must explicitly invoke --execute after current v5 evaluation or explicitly authorize earlier execution.')
    save(HERE/'execution-plan-v2.json',plan)
    print(json.dumps(dict(plan=record(HERE/'execution-plan-v2.json'),model_forward_calls=0)))


if __name__=='__main__':
    main()
