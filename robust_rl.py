"""PPO and BO/RL hybrid, compared with BO/random/transfer on measured robust cases.

Weights/checkpoints and hybrid mixing are selected only on validation current.
Economics are compute-time estimates from replay, not customer revenue claims.
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
from rl_search import score


def features(rows, selected, goal, budget, include_history=False):
    measured=[score(rows[i],goal)[0] for i in selected]
    best=rows[selected[int(np.argmin(measured))]]
    last=np.array(rows[selected[-1]]['config'])/[6,3,2]
    context=[rows[0]['reference_ua']/30,goal[0]/20,goal[1],math.log10(goal[2])/10,
             len(selected)/budget,min(measured)/30,best['worst_error_percent']/20,
             best['worst_reference_voltage_v'],math.log10(best['minimum_bandwidth_hz'])/10,
             best['geometry']['area_um2']/300,float(np.mean(measured))/30]
    encoded=[]
    for index,row in enumerate(rows):
        vector=list(np.array(row['config'])/[6,3,2])+context+list(np.array(row['config'])/[6,3,2]-last)
        if include_history:
            vector+=([1.,score(row,goal)[0]/30,row['worst_error_percent']/20,
                      row['worst_reference_voltage_v'],math.log10(row['minimum_bandwidth_hz'])/10]
                     if index in selected else [0.]*5)
        encoded.append(vector)
    return torch.tensor(encoded,dtype=torch.float32)


def state_features(model,rows,selected,goal,budget):
    return features(rows,selected,goal,budget,getattr(model,'needs_history',False))


class ActorCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.actor=nn.Sequential(nn.Linear(17,96),nn.Tanh(),nn.Linear(96,96),nn.Tanh(),nn.Linear(96,1))
        self.critic=nn.Sequential(nn.Linear(17,64),nn.Tanh(),nn.Linear(64,1))
    def forward(self,x,mask):
        logits=self.actor(x).squeeze(-1).masked_fill(mask,-torch.inf)
        return torch.distributions.Categorical(logits=logits),self.critic(x.mean(-2)).squeeze(-1)


class AttentionActorCritic(nn.Module):
    needs_history=True
    def __init__(self):
        super().__init__()
        self.encoder=nn.Sequential(nn.Linear(22,64),nn.Tanh())
        self.attention=nn.MultiheadAttention(64,4,batch_first=True)
        self.actor=nn.Sequential(nn.Linear(128,64),nn.Tanh(),nn.Linear(64,1))
        self.critic=nn.Sequential(nn.Linear(64,64),nn.Tanh(),nn.Linear(64,1))
    def forward(self,x,mask):
        single=x.ndim==2
        if single:x=x.unsqueeze(0);mask=mask.unsqueeze(0)
        encoded=self.encoder(x)
        attended,_=self.attention(encoded,encoded,encoded,key_padding_mask=~mask,need_weights=False)
        logits=self.actor(torch.cat([encoded,attended],-1)).squeeze(-1).masked_fill(mask,-torch.inf)
        pooled=(encoded*mask.unsqueeze(-1)).sum(-2)/mask.sum(-1,keepdim=True)
        value=self.critic(pooled).squeeze(-1)
        if single:logits=logits.squeeze(0);value=value.squeeze(0)
        return torch.distributions.Categorical(logits=logits),value


def goal_for(rng):
    return [float(rng.uniform(5,18)),float(rng.uniform(.8,1.15)),float(10**rng.uniform(7,8.7))]


def ei(rows, selected, goal):
    x=np.asarray([r['config'] for r in rows],float)
    x=(x-x.min(0))/np.maximum(x.max(0)-x.min(0),1)
    remaining=[i for i in range(len(rows)) if i not in selected]
    acquisition,_,_=expected_improvement(x[remaining],x[selected],[score(rows[i],goal)[0] for i in selected])
    result=np.zeros(len(rows));result[remaining]=acquisition
    total=result.sum()
    result[remaining]=result[remaining]/total if total>0 else 1/len(remaining)
    return result


def polynomial(row):
    w,l,_=row['config'];x=np.array([w/6,l/3,row['reference_ua']/30])
    return [1,*x,*(x*x),x[0]*x[1],x[0]*x[2],x[1]*x[2]]


def targets(row):
    return [math.log(max(row['worst_error_percent'],1e-8)),row['worst_reference_voltage_v'],
            math.log(row['minimum_bandwidth_hz']),math.log(row['geometry']['area_um2'])]


def fit_transfer(train,validation):
    x=np.asarray([polynomial(r) for r in train]);y=np.asarray([targets(r) for r in train])
    vx=np.asarray([polynomial(r) for r in validation]);vy=np.asarray([targets(r) for r in validation])
    scale=np.maximum(y.std(0),1e-6);best=None
    for alpha in (.001,.01,.1,1):
        regularization=np.eye(x.shape[1])*alpha;regularization[0,0]=0
        weights=np.linalg.solve(x.T@x+regularization,x.T@y)
        error=float(np.mean(((vx@weights-vy)/scale)**2))
        if best is None or error<best[0]:best=(error,weights,alpha)
    return best[1],dict(alpha=best[2],validation_standardized_mse=best[0])


def transfer_choice(rows,selected,goal,weights):
    predictions=np.asarray([polynomial(r) for r in rows])@weights
    # Only observed test measurements calibrate the transferred predictions.
    correction=np.mean(np.asarray([targets(rows[i]) for i in selected])-predictions[selected],axis=0)
    predictions+=correction
    values=[]
    for i,p in enumerate(predictions):
        proxy=dict(verification={'drc_pass':True,'lvs_pass':True},
            worst_error_percent=math.exp(float(np.clip(p[0],-20,20))),
            worst_reference_voltage_v=max(0.,float(p[1])),minimum_bandwidth_hz=math.exp(float(np.clip(p[2],-20,30))),
            geometry={'area_um2':math.exp(float(np.clip(p[3],-20,20)))})
        values.append(score(proxy,goal)[0] if i not in selected else math.inf)
    return int(np.argmin(values))


def trace(rows,goal,seed,budget,method,model=None,alpha=0.,transfer=None):
    rng=np.random.default_rng(seed);selected=rng.choice(len(rows),2,replace=False).tolist()
    while len(selected)<budget:
        remaining=[i for i in range(len(rows)) if i not in selected]
        if method=='random':index=int(rng.choice(remaining))
        elif method=='bayesian':index=int(np.argmax(ei(rows,selected,goal)))
        elif method=='transfer':index=transfer_choice(rows,selected,goal,transfer)
        else:
            mask=torch.zeros(len(rows),dtype=torch.bool);mask[selected]=True
            with torch.no_grad():dist,_=model(state_features(model,rows,selected,goal,budget),mask)
            probabilities=dist.probs.numpy()
            if method=='hybrid':probabilities=(1-alpha)*probabilities+alpha*ei(rows,selected,goal)
            index=int(np.argmax(probabilities))
        if index in selected:raise RuntimeError('Repeated design query')
        selected.append(index)
    return selected


def record(rows,goal,selected):
    first=next((k for k,i in enumerate(selected,1) if score(rows[i],goal)[1]),None)
    consumed=selected[:first] if first is not None else selected
    feasible=[i for i in selected if score(rows[i],goal)[1]]
    return dict(selected=selected,success=bool(feasible),first_feasible_query=first,
        queries_to_stop=len(consumed),estimated_oracle_seconds=sum(rows[i]['seconds'] for i in consumed),
        estimated_cold_oracle_seconds=sum(rows[i]['seconds']+rows[i]['generation_seconds'] for i in consumed),
        best_score=min(score(rows[i],goal)[0] for i in selected),
        best_area_um2=min((rows[i]['geometry']['area_um2'] for i in feasible),default=None))


def validation_score(model,rows,budget,alpha=0.,method='ppo'):
    scores=[]
    for seed in range(30):
        goal=goal_for(np.random.default_rng(90000+seed))
        scores.append(record(rows,goal,trace(rows,goal,seed,budget,method,model,alpha))['best_score'])
    return float(np.mean(scores))


def train_model(train,validation,seed,episodes,budget,output,architecture="mlp"):
    torch.manual_seed(seed);rng=np.random.default_rng(seed);model=AttentionActorCritic() if architecture=="attention" else ActorCritic()
    optimizer=torch.optim.Adam(model.parameters(),lr=3e-4)
    buffer=[];lookups=0;best=math.inf;best_state=None;history=[]
    for episode in range(episodes):
        rows=train[int(rng.choice(list(train)))];goal=goal_for(rng)
        selected=rng.choice(len(rows),2,replace=False).tolist();lookups+=2
        trajectory=[];rewards=[]
        for _ in range(budget-2):
            state=state_features(model,rows,selected,goal,budget);mask=torch.zeros(len(rows),dtype=torch.bool);mask[selected]=True
            with torch.no_grad():dist,_=model(state,mask);action=dist.sample();log=dist.log_prob(action)
            before=min(score(rows[i],goal)[0] for i in selected)
            had_success=any(score(rows[i],goal)[1] for i in selected)
            selected.append(int(action));lookups+=1
            after=min(score(rows[i],goal)[0] for i in selected)
            reward=(before-after)/10+float(not had_success and score(rows[int(action)],goal)[1])
            trajectory.append((state,mask,int(action),float(log)));rewards.append(reward)
        rewards[-1]+=float(any(score(rows[i],goal)[1] for i in selected))
        returns=np.cumsum(rewards[::-1])[::-1]
        buffer.extend((*transition,float(ret)) for transition,ret in zip(trajectory,returns))
        if (episode+1)%32==0 or episode+1==episodes:
            states=torch.stack([r[0] for r in buffer]);masks=torch.stack([r[1] for r in buffer])
            actions=torch.tensor([r[2] for r in buffer]);old_logs=torch.tensor([r[3] for r in buffer])
            targets_=torch.tensor([r[4] for r in buffer],dtype=torch.float32)
            with torch.no_grad():_,values=model(states,masks);advantages=targets_-values
            advantages=(advantages-advantages.mean())/advantages.std().clamp_min(1e-6)
            for _ in range(3):
                for indices in torch.randperm(len(buffer)).split(64):
                    dist,value=model(states[indices],masks[indices]);ratio=(dist.log_prob(actions[indices])-old_logs[indices]).exp()
                    advantage=advantages[indices]
                    loss=-torch.minimum(ratio*advantage,ratio.clamp(.8,1.2)*advantage).mean()+.5*((value-targets_[indices])**2).mean()-.01*dist.entropy().mean()
                    optimizer.zero_grad();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            buffer=[]
        if (episode+1)%500==0 or episode+1==episodes:
            value=validation_score(model,validation,budget)
            history.append(dict(episodes=episode+1,validation_mean_best_score=value))
            if value<best:best=value;best_state={k:v.detach().clone() for k,v in model.state_dict().items()}
    model.load_state_dict(best_state)
    choices={alpha:validation_score(model,validation,budget,alpha,'hybrid') for alpha in (0,.25,.5,.75,1.)}
    alpha=min(choices,key=choices.get)
    torch.save(model.state_dict(),output/f'ppo-{seed}.pt')
    return model,alpha,dict(model_seed=seed,episodes=episodes,training_cached_lookups=lookups,
                           checkpoints=history,hybrid_validation_scores=choices,selected_alpha=alpha)


def validate(folder,rows):
    provenance=json.loads((folder/'provenance.json').read_text());n=len(provenance['configs'])
    seen=set()
    for r in rows:
        key=(r['reference_ua'],r['candidate'])
        if key in seen:raise ValueError('Duplicate case')
        seen.add(key)
        current=r['reference_ua'];expected='test' if current==30 else 'validation' if current==15 else 'train'
        if current not in (10,15,20,30) or r['split']!=expected:raise ValueError('Invalid split')
        if not 0<=r['candidate']<n or r['config']!=provenance['configs'][r['candidate']]:raise ValueError('Invalid candidate')
        design=(folder/r['design']).resolve()
        if folder.resolve() not in design.parents:raise ValueError('Evidence outside dataset')
        for name,keyhash in (('layout.gds','gds_sha256'),('rc/extracted_rc.spice','rc_sha256')):
            if hashlib.sha256((design/name).read_bytes()).hexdigest()!=r[keyhash]:raise ValueError('Changed physical evidence')
        if not r['verification']['drc_pass'] or not r['verification']['lvs_pass'] or not r['extraction']['all_four_nets_emitted']:
            raise ValueError('Unverified physical evidence')
        expected_conditions={(c,t) for c in provenance['corners'] for t in provenance['temperatures_c']}
        if len(r['electrical'])!=len(expected_conditions) or {(m['corner'],m['temperature_c']) for m in r['electrical']}!=expected_conditions:
            raise ValueError('Incomplete electrical coverage')
        if any(m['reference_ua']!=current for m in r['electrical']):raise ValueError('Incorrect simulation current')
        samples=r['mismatch']
        if len(samples)!=provenance['samples'] or len({m['seed'] for m in samples})!=len(samples):raise ValueError('Incomplete mismatch samples')
        errors=[m['worst_error_percent'] for m in samples]
        expected_error=max(max(m['worst_error_percent_0p6_to_1p6v'] for m in r['electrical']),float(np.quantile(errors,.9)))
        if not all(math.isfinite(v) and v>=0 for v in errors) or abs(r['worst_error_percent']-expected_error)>1e-9:
            raise ValueError('Invalid robust error label')
    if seen!={(current,i) for current in (10,15,20,30) for i in range(n)}:raise ValueError('Incomplete grid')
    return provenance


def run(args):
    torch.set_num_threads(1);output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    raw=(args.dataset/'rows.json').read_bytes();rows=json.loads(raw);validate(args.dataset,rows)
    groups={current:sorted([r for r in rows if r['reference_ua']==current],key=lambda r:r['candidate']) for current in (10,15,20,30)}
    train={current:groups[current] for current in (10,20)};validation=groups[15];test=groups[30]
    if not 3<=args.budget<=len(test):raise ValueError('Invalid budget')
    transfer,transfer_meta=fit_transfer([*groups[10],*groups[20]],validation)
    records=[];training=[];start=time.perf_counter()
    for model_seed in range(args.models):
        model,alpha,history=train_model(train,validation,model_seed,args.episodes,args.budget,output,args.architecture)
        training.append(history)
        for task in range(args.tasks):
            goal=goal_for(np.random.default_rng(100000+task))
            for method in ('ppo','hybrid','bayesian','random','transfer'):
                selected=trace(test,goal,task,args.budget,method,model,alpha,transfer)
                records.append(dict(model_seed=model_seed,task_seed=task,method=method,goal=goal,**record(test,goal,selected)))
        print(f'Model {model_seed} complete; validation selected hybrid alpha={alpha}',flush=True)
    summary={}
    for method in ('ppo','hybrid','bayesian','random','transfer'):
        items=[r for r in records if r['method']==method]
        summary[method]=dict(evaluations=len(items),successes=sum(r['success'] for r in items),
            mean_queries_to_stop=float(np.mean([r['queries_to_stop'] for r in items])),
            mean_estimated_oracle_seconds=float(np.mean([r['estimated_oracle_seconds'] for r in items])),
            mean_best_score=float(np.mean([r['best_score'] for r in items])))
    # One deployment model's acquisition cost; shared labeling is charged once.
    upfront=sum(r['seconds'] for r in rows if r['split']!='test')+sum(r['generation_seconds'] for r in groups[10])
    compute_seconds=time.perf_counter()-start
    economics={}
    for method in ('ppo','hybrid','transfer'):
        saved=summary['bayesian']['mean_estimated_oracle_seconds']-summary[method]['mean_estimated_oracle_seconds']
        success_ok=summary[method]['successes']>=summary['bayesian']['successes']
        economics[method]=dict(seconds_saved_per_task_vs_bayesian=saved,success_count_at_least_bayesian=success_ok,
            estimated_break_even_tasks=math.ceil((upfront+compute_seconds)/saved) if saved>0 and success_ok else None)
    result=dict(schema_version=1,dataset_sha256=hashlib.sha256(raw).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),budget=args.budget,architecture=args.architecture,
        training=training,transfer=transfer_meta,summary=summary,records=records,
        compute_seconds=compute_seconds,estimated_upfront_oracle_seconds=upfront,economics=economics,
        limitations=['Measured-table replay; no live deployment productivity measurement',
        'One circuit topology; held-out reference current only','Small-sample TT/27C mismatch quantile, not production yield',
        'Test tasks repeated across model seeds; baseline repeats are correlated',
        'Break-even uses measured oracle elapsed-time estimates; excludes license, engineering, integration and customer costs',
        'Primary query cost assumes cached layouts and fresh current characterization; cold-generation cost is recorded separately'])
    (output/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(summary=summary,economics=economics),indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--architecture',choices=['mlp','attention'],default='mlp')
    p.add_argument('--episodes',type=int,default=2500);p.add_argument('--models',type=int,default=3)
    p.add_argument('--tasks',type=int,default=100);p.add_argument('--budget',type=int,default=6)
    a=p.parse_args()
    if min(a.episodes,a.models,a.tasks)<1:p.error('Positive counts required')
    run(a)
