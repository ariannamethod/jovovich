#!/usr/bin/env python3
"""Independent bitset aggregation of an already-completed readout run.

This performs only saved-prediction checks/counts, never model arithmetic or fit.
Run only after the parent agent announces completion and makes outputs available.
"""
import argparse,hashlib,json,math
from pathlib import Path


def digest(path):
    raw=path.read_bytes();return {'path':str(path.resolve()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def load(path):
    def nonfinite(v):raise ValueError('Nonfinite literal '+v)
    return json.loads(path.read_text(),parse_constant=nonfinite)


def parse_view(path, rows, masks):
    records=[json.loads(line) for line in path.read_text().splitlines()]
    configurations=[v for v in records if v['type']=='configuration'];completions=[v for v in records if v['type']=='completion']
    assert len(configurations)==len(completions)==1
    assert completions[0]['fits']==2002 and completions[0]['failed_fits']==0 and completions[0]['all_converged'] is True
    seen_keys=set();heldout_correct={k:0 for k in range(-1,99)};heldout_seen={k:0 for k in range(-1,99)}
    heldout_pred={k:{} for k in range(-1,99)};capacity=[];maxgrad=0;maxiter=0;fits=0;norms=0
    for record in records:
        if record['type']=='normalization':
            f=record['heldout_family'];expected=[r['index'] for r in rows if f<0 or r['family_index']!=f]
            assert record['training_rows']==expected;norms+=1
            continue
        if record['type']!='fit':continue
        fits+=1;p=record['permutation'];f=record['heldout_family'];mode=record['mode'];key=(mode,p,f)
        assert key not in seen_keys;seen_keys.add(key)
        assert record['converged'] is True and record['status']=='gradient_tolerance'
        assert 0<=record['gradient_inf']<=1e-8 and 0<=record['iterations']<=100
        maxgrad=max(maxgrad,record['gradient_inf']);maxiter=max(maxiter,record['iterations'])
        allmask=0;hitmask=0;predictions={}
        for prediction in record['predictions']:
            i=prediction['row'];row=rows[i];bit=1<<i
            assert 0<=i<52 and not allmask&bit;allmask|=bit
            assert prediction['family']==row['family_index'] and prediction['pair']==row['pair_index']
            assert prediction['subset']==int(row['same_full_diff_subset'])
            label=row['label'] if p<0 else row['label']^int(masks[p][row['family_index']])
            assert prediction['label']==label and prediction['prediction']==int(prediction['score']>0)
            assert math.isfinite(prediction['score']) and math.isfinite(prediction['probability'])
            assert 0<=prediction['probability']<=1
            if prediction['prediction']==label:hitmask|=bit
            predictions[i]=prediction
        expected_rows=range(52) if mode=='interpolation' else [r['index'] for r in rows if r['family_index']==f]
        expected_mask=sum(1<<i for i in expected_rows)
        assert allmask==expected_mask
        if mode=='heldout':
            assert record['lambda']==.01 and 0<=f<20 and -1<=p<99
            assert not heldout_seen[p]&allmask
            heldout_seen[p]|=allmask;heldout_correct[p]|=hitmask;heldout_pred[p].update(predictions)
        else:
            assert mode=='interpolation' and f==-1 and p in (-1,0) and record['lambda']==1e-8
            assert hitmask.bit_count()==record['train_correct']
            capacity.append({'permutation':p,'correct':hitmask.bit_count(),'ce':record['train_ce'],'capacity_success':hitmask.bit_count()==52 and record['train_ce']<=.001,'converged':True,'gradient_inf':record['gradient_inf']})
    assert fits==2002 and norms==21
    expected={('heldout',p,f) for f in range(20) for p in range(-1,99)}|{('interpolation',-1,-1),('interpolation',0,-1)}
    assert seen_keys==expected and all(v==(1<<52)-1 for v in heldout_seen.values())
    pairbits={}
    for row in rows:pairbits[row['pair_index']]=pairbits.get(row['pair_index'],0)|(1<<row['index'])
    assert len(pairbits)==26 and all(b.bit_count()==2 for b in pairbits.values())
    same_pairs={r['pair_index'] for r in rows if r['same_full_diff_subset']}
    stats={}
    for p,hits in heldout_correct.items():
        labels={i:(r['label'] if p<0 else r['label']^int(masks[p][r['family_index']])) for i,r in enumerate(rows)}
        passing=[pair for pair,bits in pairbits.items() if hits&bits==bits]
        stats[p]={'correct':hits.bit_count(),'complete_pairs':len(passing),'pair_indices':passing,'correct_concern':sum(bool(hits&(1<<i)) for i in range(52) if labels[i]==1),'correct_clean':sum(bool(hits&(1<<i)) for i in range(52) if labels[i]==0),'same_full_diff_complete_pairs':sum(pair in same_pairs for pair in passing)}
    family=[]
    for f in range(20):
        rr=[r for r in rows if r['family_index']==f];bits=sum(1<<r['index'] for r in rr);pairids={r['pair_index'] for r in rr}
        family.append({'family':rr[0]['family'],'rows':len(rr),'correct':(heldout_correct[-1]&bits).bit_count(),'pairs':len(pairids),'complete_pairs':sum(pair in stats[-1]['pair_indices'] for pair in pairids)})
    margin_rows=sorted([{'row':i,'id':rows[i]['id'],'family':rows[i]['family'],'score':prediction['score'],'absolute_score':abs(prediction['score']),'label':prediction['label'],'prediction':prediction['prediction'],'correct':prediction['label']==prediction['prediction']} for i,prediction in heldout_pred[-1].items()],key=lambda r:r['absolute_score'])
    threshold_counts={str(t):sum(abs(p['score'])<=t for p in heldout_pred[-1].values()) for t in [0,1e-8,1e-6,1e-4,1e-3]}
    margin_audit={'minimum_absolute_score':margin_rows[0]['absolute_score'],'smallest_ten':margin_rows[:10],'absolute_score_at_most_threshold':threshold_counts,'interpretation':'Descriptive sensitivity only; prediction threshold remains exactly0, tie remainsclean. Gradient-infinity stopping tolerance is not a calibrated bound on heldout score uncertainty.'}
    return {'observed':stats[-1],'permutations':[stats[p] for p in range(99)],'capacity':sorted(capacity,key=lambda r:r['permutation']),'families':family,'fits':fits,'max_gradient_inf':maxgrad,'max_iterations':maxiter,'observed_margin_audit':margin_audit,'source':digest(path)}


def rank_receipt(observed,null):
    higher=sum(v>observed for v in null);ties=sum(v==observed for v in null);lower=sum(v<observed for v in null)
    assert len(null)==99 and higher+ties+lower==99
    return {'observed':observed,'reference_greater':higher,'reference_equal':ties,'reference_less':lower,'upper_tail_numerator_with_identity':1+higher+ties,'denominator':100,'upper_tail_fraction':(1+higher+ties)/100,'null_min':min(null),'null_max':max(null)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run=args.run;rows=load(run/'readout-rows.json')['rows'];masks=load(run/'readout-masks.json')['masks']
    assert [r['index'] for r in rows]==list(range(52)) and len(masks)==99
    z=parse_view(run/'state-fits.jsonl',rows,masks);n=parse_view(run/'nuisance-fit-fits.jsonl',rows,masks)
    comparisons={'z_complete_pairs':rank_receipt(z['observed']['complete_pairs'],[r['complete_pairs'] for r in z['permutations']]),'nuisance_complete_pairs':rank_receipt(n['observed']['complete_pairs'],[r['complete_pairs'] for r in n['permutations']]),'paired_z_minus_nuisance_complete_pairs':rank_receipt(z['observed']['complete_pairs']-n['observed']['complete_pairs'],[a['complete_pairs']-b['complete_pairs'] for a,b in zip(z['permutations'],n['permutations'])])}
    official=load(run/'readout-summary.json')
    for key,independent in [('z',z),('nuisance',n)]:
        reported=official['views'][key]
        for ours,theirs in zip([independent['observed']]+independent['permutations'],[reported['observed']]+reported['permutations']):
            for field in ['correct','complete_pairs','correct_concern','correct_clean','same_full_diff_complete_pairs']:assert ours[field]==theirs[field],(key,field,ours,theirs)
            assert sorted(ours['pair_indices'])==sorted(theirs['complete_pair_indices'])
        assert independent['capacity']==[{k:r[k] if k!='ce' else r['train_ce'] for k in ['permutation','correct','ce','capacity_success','converged','gradient_inf']} for r in reported['capacity']]
    for key,ours in comparisons.items():
        theirs=official['permutation_references'][key]
        assert ours['observed']==theirs['observed']
        assert ours['reference_greater']+ours['reference_equal']==theirs['reference_at_least_observed']
        assert ours['upper_tail_fraction']==theirs['plus_one_upper_tail_fraction']
    receipt=load(run/'readout-run.json');assert receipt['status']=='completed' and receipt['all_frozen_inputs_unchanged'] is True
    for phase in receipt['phases']:
        assert phase['returncode']==0
        for item in [phase['stdout'],phase['stderr']]+phase['created_files']:
            actual=digest(Path(item['path']));assert actual['sha256']==item['sha256'] and actual['bytes']==item['bytes']
    result={'status':'PASS: independent bitset recount matches official counts and all three permutation tails','independent_method':'Unique heldout row bits accumulated independently per label mask; a pair passes iff both row bits are present. Count strictgreater/equal/less reference scores directly, with identity added once.','z':z,'nuisance':n,'rank_receipts':comparisons,'source_summary':digest(run/'readout-summary.json'),'source_run_receipt':digest(run/'readout-run.json'),'auditor_source':digest(Path(__file__)),'boundaries':['No inference, fitting, normalizing, logits or score tuning performed by auditor.','Binary separation at supplied common prefix does not establish natural complete-review competence.','Training interpolation is not transfer; heldout families are templates rather than independent semantic domains.','Seven nuisance features do not exhaust nonsemantic shortcuts; permutation exchangeability is an exploratory assumption.']}
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({'status':result['status'],'z_observed':z['observed'],'nuisance_observed':n['observed'],'tails':comparisons}))

if __name__=='__main__':main()
