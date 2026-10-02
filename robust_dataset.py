"""Generate measured experimental RC/mismatch cases for robust search research."""
import argparse
import hashlib
import itertools
import json
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
from physical_flow import ROOT, PDK_BUILD, generate, verify, simulate
from rc_probe import run as extract_rc
from mismatch_probe import sample

CURRENTS=(10,15,20,30)
CONFIGS=list(itertools.product((1,2,4,6),(.5,1,1.5,2,3),(2,)))


def build(task):
    index, config, output_name, samples=task
    output=Path(output_name);design=output/'designs'/f'candidate-{index:03d}'
    design.mkdir(parents=True,exist_ok=False)
    pdk=ROOT/'pdks/sky130A';os.environ.update(PDK_ROOT=str(pdk.parent),PDKPATH=str(pdk))
    started=time.perf_counter()
    _,geometry=generate(*config,design)
    verification=verify(design,pdk)
    if not (verification['drc_pass'] and verification['lvs_pass']):
        raise RuntimeError(f'Candidate {index} failed DRC/LVS; evidence retained')
    rc=design/'rc';extract_rc(design,rc)
    extraction=json.loads((rc/'summary.json').read_text())
    netlist=(rc/'extracted_rc.spice').read_text()
    generation_seconds=time.perf_counter()-started
    rows=[]
    for current in CURRENTS:
        start=time.perf_counter();case=output/f'current-{current}/candidate-{index:03d}'
        case.mkdir(parents=True,exist_ok=False)
        split='test' if current==30 else 'validation' if current==15 else 'train'
        electrical=[]
        for corner,temperature in itertools.product(('tt','ss','ff'),(-20,27,85)):
            m=simulate(netlist,case/f'{corner}-{temperature}',pdk,corner,temperature,reference_ua=current)
            electrical.append(m)
        # Independent labeling streams for train/development/test currents.
        seed_base={10:20000,20:30000,15:40000,30:50000}[current]
        mismatch=[sample(netlist,case/f'mismatch-{seed}',seed,True,reference_ua=current)
                  for seed in range(seed_base,seed_base+samples)]
        errors=[r['worst_error_percent'] for r in mismatch]
        corner_error=max(m['worst_error_percent_0p6_to_1p6v'] for m in electrical)
        robust_error=max(corner_error,float(np.quantile(errors,.9,method='linear')))
        bandwidths=[m['bandwidth_3db_hz'] for m in electrical]
        if any(b is None or b<=0 for b in bandwidths):
            raise RuntimeError('Missing measured bandwidth crossing')
        row=dict(candidate=index,config=list(config),reference_ua=current,split=split,
            geometry=geometry,verification=verification,electrical=electrical,mismatch=mismatch,
            worst_error_percent=robust_error,corner_error_percent=corner_error,
            mismatch_p90_error_percent=float(np.quantile(errors,.9)),
            worst_reference_voltage_v=max(m['max_reference_voltage_v'] for m in electrical),
            minimum_bandwidth_hz=min(bandwidths),seconds=time.perf_counter()-start,
            generation_seconds=generation_seconds,design=str(design.relative_to(output)),
            evidence=str(case.relative_to(output)),extraction=extraction,
            gds_sha256=hashlib.sha256((design/'layout.gds').read_bytes()).hexdigest(),
            rc_sha256=hashlib.sha256(netlist.encode()).hexdigest())
        (case/'case.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
        rows.append(row)
        print(f'candidate={index} current={current} robust_error={robust_error:.3f}%',flush=True)
    return rows


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'source').mkdir()
    names=('robust_dataset.py','physical_flow.py','mirror_search.py','rc_probe.py','mismatch_probe.py')
    for name in names:shutil.copyfile(ROOT/name,output/'source'/name)
    provenance=dict(schema_version=2,pdk_build=PDK_BUILD,configs=CONFIGS,
        source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names},
        corners=['tt','ss','ff'],temperatures_c=[-20,27,85],samples=args.samples,
        objective='max(nine-corner DC error, TT/27C empirical mismatch 90th-percentile DC error)',
        limitations=['One upstream topology; experimental detailed RC',
        'Small-sample mismatch quantile, not production yield','No bandwidth mismatch, process Monte Carlo or spatial gradients',
        'Same geometry grid across current splits; no topology generalization'])
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    rows=[];started=time.perf_counter()
    tasks=[(i,c,str(output),args.samples) for i,c in enumerate(CONFIGS)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for batch in pool.map(build,tasks):
            rows.extend(batch)
            (output/'rows.json').write_text(json.dumps(rows,indent=2,allow_nan=False)+'\n')
    (output/'timing.json').write_text(json.dumps(dict(wall_seconds=time.perf_counter()-started,
        workers=args.workers,cases=len(rows)),indent=2))
    print(f'Completed {len(rows)} robust cases',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=30);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args()
    if a.samples<10 or a.workers<1:p.error('Require at least 10 samples and one worker')
    run(a)
