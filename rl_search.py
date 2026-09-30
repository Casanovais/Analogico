"""REINFORCE acquisition policy over a measured layout grid, with held-out current.

The environment replays real verification/simulation measurements. No test-current
labels are accessed during training. This is sequential sizing/search, not a
transistor placement or routing policy. Training oracle exposure is reported.
"""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path
import numpy as np
import torch
from torch import nn
from mirror_search import expected_improvement


def score(row, goal):
    if not row['verification']['drc_pass'] or not row['verification']['lvs_pass']:
        return 30., False
    values = [row.get(k) for k in ('worst_error_percent','worst_reference_voltage_v','minimum_bandwidth_hz')]
    if any(v is None or isinstance(v,bool) or not math.isfinite(v) or v < 0 for v in values) or values[2] == 0:
        return 30., False
    error, voltage, bandwidth = values
    penalty = max(0,error/goal[0]-1)+max(0,voltage/goal[1]-1)+max(0,goal[2]/bandwidth-1)
    return min(30., math.log(row['geometry']['area_um2']/100)+10*penalty), penalty == 0


def inputs(rows, selected, goal, budget):
    scores = [score(rows[i],goal)[0] for i in selected]
    best = selected[int(np.argmin(scores))]
    previous = np.array(rows[selected[-1]]['config'][:2])/[4,2]
    context = [rows[0]['reference_ua']/30, goal[0]/10, goal[1], math.log10(goal[2])/10,
               len(selected)/budget, min(scores)/30,
               (rows[best].get('worst_error_percent') or 100)/100,
               (rows[best].get('worst_reference_voltage_v') or 2)/2]
    return torch.tensor([list(np.array(r['config'][:2])/[4,2])+context+
                        list(np.array(r['config'][:2])/[4,2]-previous) for r in rows],dtype=torch.float32)


def distribution(policy, rows, selected, goal, budget):
    logits = policy(inputs(rows,selected,goal,budget)).flatten()
    mask = torch.zeros(len(rows),dtype=torch.bool)
    mask[selected] = True
    return torch.distributions.Categorical(logits=logits.masked_fill(mask,-torch.inf))


def policy_model():
    return nn.Sequential(nn.Linear(12,64),nn.Tanh(),nn.Linear(64,64),nn.Tanh(),nn.Linear(64,1))


def episode(policy, rows, goal, seed, budget=8, training=False):
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(rows),4,replace=False).tolist()
    logs, entropies, rewards = [], [], []
    for _ in range(budget-4):
        before = min(score(rows[i],goal)[0] for i in selected)
        dist = distribution(policy,rows,selected,goal,budget)
        action = dist.sample() if training else torch.argmax(dist.probs)
        logs.append(dist.log_prob(action)); entropies.append(dist.entropy())
        selected.append(int(action))
        after = min(score(rows[i],goal)[0] for i in selected)
        rewards.append((before-after)/10)
    success = any(score(rows[i],goal)[1] for i in selected)
    rewards[-1] += float(success)
    return selected, logs, entropies, rewards


def baseline(rows,goal,seed,strategy,budget=8):
    rng=np.random.default_rng(seed)
    selected=rng.choice(len(rows),4,replace=False).tolist()
    x=np.array([r['config'][:2] for r in rows],float)
    x=(x-x.min(0))/np.maximum(x.max(0)-x.min(0),1)
    for _ in range(budget-4):
        remaining=[i for i in range(len(rows)) if i not in selected]
        if strategy == 'random':
            index=int(rng.choice(remaining))
        else:
            acquisition,_,_=expected_improvement(x[remaining],x[selected],[score(rows[i],goal)[0] for i in selected])
            index=remaining[int(np.argmax(acquisition))]
        selected.append(index)
    return selected


def validate_dataset(folder, rows):
    provenance=json.loads((folder/'provenance.json').read_text())
    spec=provenance['specification']
    expected={(c,t) for c in spec['corners'] for t in spec['temperatures_c']}
    seen=set()
    for row in rows:
        if row['reference_ua'] not in (10,20,30) or not 0<=row['candidate']<12:
            raise ValueError('Unknown current or candidate')
        if row['config']!=provenance['configs'][row['candidate']]:
            raise ValueError('Candidate geometry mismatch')
        key=(row['reference_ua'],row['candidate'])
        if key in seen: raise ValueError('Duplicate measured case')
        seen.add(key)
        expected_split='test' if row['reference_ua']==30 else 'train'
        if row['split']!=expected_split: raise ValueError('Split/current mismatch')
        evidence=(folder/row['evidence']).resolve()
        if folder.resolve() not in evidence.parents: raise ValueError('Evidence outside dataset')
        if hashlib.sha256((evidence/'layout.gds').read_bytes()).hexdigest()!=row['gds_sha256']:
            raise ValueError('Changed measured layout')
        measures=row['electrical']
        actual={(r['corner'],r['temperature_c']) for r in measures}
        if actual!=expected or len(measures)!=len(expected): raise ValueError('Missing or duplicate simulation coverage')
        if any(r['reference_ua']!=row['reference_ua'] for r in measures): raise ValueError('Wrong simulation current')
        if any(not math.isfinite(r['worst_error_percent_0p6_to_1p6v']) for r in measures):
            raise ValueError('Nonfinite measured error')
        maxima=max(r['worst_error_percent_0p6_to_1p6v'] for r in measures)
        if abs(maxima-row['worst_error_percent'])>1e-10: raise ValueError('Inconsistent aggregate error')
    if seen!={(current,index) for current in (10,20,30) for index in range(12)}:
        raise ValueError('Incomplete dataset grid')
    return provenance


def run(args):
    torch.set_num_threads(1)
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=False)
    raw=(args.dataset/'rows.json').read_bytes()
    all_rows=json.loads(raw)
    validate_dataset(args.dataset,all_rows)
    train={current:sorted([r for r in all_rows if r['split']=='train' and r['reference_ua']==current],key=lambda r:r['candidate']) for current in (10,20)}
    test=sorted([r for r in all_rows if r['split']=='test' and r['reference_ua']==30],key=lambda r:r['candidate'])
    if any(len(rows)!=12 for rows in [*train.values(),test]):
        raise ValueError('Expected complete 12-candidate grids for 10/20/30 uA')
    results=[]; histories=[]; started=time.perf_counter()
    for model_seed in range(args.models):
        torch.manual_seed(model_seed); rng=np.random.default_rng(model_seed)
        policy=policy_model(); optimizer=torch.optim.Adam(policy.parameters(),lr=0.001)
        moving=0.; training_success=0
        for step in range(args.episodes):
            rows=train[int(rng.choice([10,20]))]
            goal=[float(rng.uniform(3,10)),float(rng.uniform(.85,1.15)),float(10**rng.uniform(7,8.5))]
            selected,logs,entropy,rewards=episode(policy,rows,goal,int(rng.integers(1e9)),training=True)
            returns=np.cumsum(rewards[::-1])[::-1].copy()
            training_success+=int(any(score(rows[i],goal)[1] for i in selected))
            loss=sum(-log*(float(value)-moving)-0.01*ent for log,value,ent in zip(logs,returns,entropy))/len(logs)
            optimizer.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(policy.parameters(),1.); optimizer.step()
            moving=.95*moving+.05*float(returns.mean())
        torch.save(policy.state_dict(),output/f'policy-{model_seed}.pt')
        histories.append(dict(model_seed=model_seed,episodes=args.episodes,oracle_lookups=args.episodes*8,
                              training_success_fraction=training_success/args.episodes))
        # Goals and starts are identical across strategies and models.
        for task_seed in range(args.tasks):
            task_rng=np.random.default_rng(10000+task_seed)
            goal=[float(task_rng.uniform(3,10)),float(task_rng.uniform(.85,1.15)),float(10**task_rng.uniform(7,8.5))]
            exhaustive=[i for i,r in enumerate(test) if score(r,goal)[1]]
            for strategy in ('rl','random','bayesian'):
                with torch.no_grad():
                    selected=episode(policy,test,goal,task_seed)[0] if strategy=='rl' else baseline(test,goal,task_seed,strategy)
                feasible=[i for i in selected if score(test[i],goal)[1]]
                best=min((test[i]['geometry']['area_um2'] for i in feasible),default=None)
                optimum=min((test[i]['geometry']['area_um2'] for i in exhaustive),default=None)
                results.append(dict(model_seed=model_seed,task_seed=task_seed,strategy=strategy,
                    goal=goal,selected=selected,queries=len(selected),success=bool(feasible),
                    best_area_um2=best,grid_optimum_area_um2=optimum,
                    best_score=min(score(test[i],goal)[0] for i in selected)))
        print(f'Model {model_seed}: training and held-out evaluation complete',flush=True)
    summary={strategy:dict(trials=len(records),successful_trials=sum(r['success'] for r in records),
        mean_best_score=float(np.mean([r['best_score'] for r in records])),
        median_successful_area_um2=float(np.median([r['best_area_um2'] for r in records if r['success']])) if any(r['success'] for r in records) else None)
        for strategy in ('rl','random','bayesian') for records in [[r for r in results if r['strategy']==strategy]]}
    report=dict(dataset_sha256=hashlib.sha256(raw).hexdigest(),source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        algorithm='REINFORCE, 2x64 tanh network, masked previously queried candidates; improvement plus final feasibility reward',
        torch_version=torch.__version__,training=histories,summary=summary,results=results,seconds=time.perf_counter()-started,
        limitations=['Single topology and geometry grid; held-out current only','Measured table replay, not live tool RL',
        'Training data generation and lookups are extra costs versus untrained baselines',
        'Repeated task seeds across models are correlated; no significance claim',
        'Capacitance-only extraction; no mismatch/yield or foundry signoff'])
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--episodes',type=int,default=1000); p.add_argument('--models',type=int,default=3)
    p.add_argument('--tasks',type=int,default=50)
    args=p.parse_args()
    if min(args.episodes,args.models,args.tasks)<=0: p.error('Counts must be positive')
    run(args)
