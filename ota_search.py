"""Live Bayesian operating-point tuning with full physical/PVT qualification.

Bias currents are tuned on a fixed independently checked OTA layout. This is
not a claim of RL-designed transistor geometry or foundry signoff.
"""
import argparse
import copy
import hashlib
import itertools
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from mirror_search import expected_improvement
from ota_flow import characterize,meets,run as qualify_ota
from physical_flow import ROOT


def objective(metrics,spec):
    if metrics['unity_gain_hz'] is None or metrics['phase_margin_deg'] is None:
        return 100.
    excess=sum(max(0,spec[limit]/max(metrics[key],1e-9)-1) for key,limit in
        (('low_frequency_gain_db','minimum_gain_db'),('unity_gain_hz','minimum_unity_gain_hz'),
         ('phase_margin_deg','minimum_phase_margin_deg')))
    excess+=max(0,metrics['power_mw']/spec['maximum_power_mw']-1)
    excess+=max(0,metrics['worst_tracking_error_mv']/spec['maximum_tracking_error_mv']-1)
    return math.log(max(metrics['power_mw'],1e-12))+10*excess


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    base=args.design.resolve();prior=json.loads((base/'summary.json').read_text())
    if not prior['verification']['drc_pass'] or not prior['verification']['lvs_pass']:
        raise ValueError('Start from an independently verified OTA')
    if hashlib.sha256((base/'layout.gds').read_bytes()).hexdigest()!=prior['layout_sha256']:
        raise ValueError('Prior layout evidence hash changed')
    spec=json.loads(args.spec.read_text());pdk=ROOT/'pdks/sky130A'
    candidates=list(itertools.product((2,4,6,8),(20,40,80,120)))
    x=np.asarray(candidates,dtype=float);x=(x-x.min(0))/(x.max(0)-x.min(0))
    cache={};traces=[];initial=np.random.default_rng(7).choice(len(candidates),4,replace=False).tolist()
    def evaluate(index):
        if index in cache:return cache[index]
        started=time.perf_counter();local=copy.deepcopy(spec)
        local['diffpair_bias_ua'],local['common_source_bias_ua']=candidates[index]
        folder=output/'nominal'/f'candidate-{index:03d}';folder.mkdir(parents=True)
        (folder/'specification.json').write_text(json.dumps(local,indent=2)+'\n')
        measurements=[dict(source=source,**characterize((base/f'{source}.spice').read_text(),folder/source,pdk,local,'tt',27))
                      for source in ('schematic','extracted_capacitance')]
        result=dict(candidate=index,currents_ua=candidates[index],electrical=measurements,
            score=max(objective(m,local) for m in measurements),
            nominal_feasible=all(meets(m,local) for m in measurements),seconds=time.perf_counter()-started)
        (folder/'evaluation.json').write_text(json.dumps(result,indent=2)+'\n');cache[index]=result
        print(f'OTA candidate {index}: bias={candidates[index]}, feasible={result["nominal_feasible"]}, score={result["score"]:.3f}',flush=True)
        return result
    for method in ('bayesian','random'):
        selected=[];rng=np.random.default_rng(107)
        for step in range(args.budget):
            if step<4:index=initial[step]
            else:
                remaining=[i for i in range(len(candidates)) if i not in selected]
                if method=='random':index=int(rng.choice(remaining))
                else:
                    acquisition,_,_=expected_improvement(x[remaining],x[selected],[cache[i]['score'] for i in selected])
                    index=remaining[int(np.argmax(acquisition))]
            result=evaluate(index);selected.append(index)
        traces.append(dict(method=method,selected=selected,query_budget=args.budget,
            best_score=min(cache[i]['score'] for i in selected),
            nominal_success=any(cache[i]['nominal_feasible'] for i in selected)))
    # Audit remaining grid points after adaptive search; this cannot influence its choices.
    for index in range(len(candidates)):evaluate(index)
    feasible=sorted([i for i,r in cache.items() if r['nominal_feasible']],key=lambda i:cache[i]['score'])
    full=[];winner=None
    for index in feasible:
        local=copy.deepcopy(spec);local['diffpair_bias_ua'],local['common_source_bias_ua']=candidates[index]
        spec_path=output/f'candidate-{index:03d}-specification.json';spec_path.write_text(json.dumps(local,indent=2)+'\n')
        folder=output/'qualified'/f'candidate-{index:03d}'
        try:qualify_ota(SimpleNamespace(spec=spec_path,design=base,output=folder))
        except RuntimeError:
            path=folder/'summary.json'
            if not path.is_file():raise
            result=json.loads(path.read_text())
            if len(result['electrical'])!=2*len(local['corners'])*len(local['temperatures_c']):raise
        result=json.loads((folder/'summary.json').read_text())
        full.append(dict(candidate=index,specification_pass=result['specification_pass'],evidence=str(folder.relative_to(output))))
        if result['specification_pass']:winner=index;break
    summary=dict(layout_sha256=prior['layout_sha256'],source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        specification=spec,candidates=candidates,experiments=traces,nominal_evaluations=list(cache.values()),
        full_corner_checks=full,qualified_candidate=winner,
        limitations=['One fixed layout; bias-current tuning only','Nominal BO followed by full corner/source qualification',
                     'No OTA mismatch or foundry signoff','One paired search seed; no statistical superiority claim'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('Qualified OTA candidate:',winner,flush=True)
    if winner is None:raise RuntimeError('No candidate passed the unchanged full OTA specification')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--design',type=Path,required=True)
    p.add_argument('--spec',type=Path,default=ROOT/'examples/ota_spec.json');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--budget',type=int,default=10);a=p.parse_args()
    if not 4<=a.budget<=16:p.error('Budget must be between 4 and 16')
    run(a)
