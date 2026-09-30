"""Seeded SKY130 local-mismatch probe, with reproducibility and activation controls.

This samples TT/27C DC only and must not be described as production yield.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import numpy as np
from physical_flow import ROOT, command, mirror_instance


def sample(netlist, output, seed, enabled, pair=False):
    output.mkdir(parents=True,exist_ok=False)
    models=ROOT/'pdks/sky130A/libs.ref/sky130_fd_pr/spice'
    (output/'.spiceinit').write_text(f'set ngbehavior=hsa\nset ng_nomodcheck\nset sourcepath = ( . {models} )\nset rndseed = {seed}\n')
    body='''VGG G 0 0.8
VD1 D1 0 1
VD2 D2 0 1
X1 D1 G 0 0 sky130_fd_pr__nfet_01v8 w=2 l=1.5
X2 D2 G 0 0 sky130_fd_pr__nfet_01v8 w=2 l=1.5
''' if pair else netlist+f'\nIREF 0 VREF 20u\nVOUT VOUT 0 1\n{mirror_instance(netlist)}\n'
    deck=f'''Mismatch probe
.include "{models/'sky130_fd_pr__nfet_01v8__tt.corner.spice'}"
.option scale=1e-6
.param mc_mm_switch={int(enabled)} mc_pr_switch=0
.include "{models/'sky130_fd_pr__nfet_01v8__mismatch.corner.spice'}"
.temp 27
{body}
.control
set wr_vecnames
set wr_singlescale
'''
    if pair:
        deck+='op\nwrdata measurement.dat i(VD1) i(VD2)\n'
    else:
        deck+='dc VOUT 0.6 1.6 0.05\nwrdata measurement.dat v(VOUT) i(VOUT)\n'
    deck+='quit\n.endc\n.end\n'
    (output/'testbench.spice').write_text(deck)
    (output/'driver.spice').write_text(f'Mismatch control driver\n.control\nsetseed {seed}\nsource testbench.spice\n.endc\n.end\n')
    command(['ngspice','-b','driver.spice'],output,output/'ngspice.log')
    measurements=np.atleast_2d(np.loadtxt(output/'measurement.dat',skiprows=1))
    if not np.all(np.isfinite(measurements)): raise ValueError('Invalid measurement')
    if pair:
        return float(measurements[0,1]/measurements[0,2])
    ratios=-measurements[:,2]/20e-6
    return dict(seed=seed,worst_error_percent=float(np.max(np.abs(ratios-1))*100),
                ratio_at_1v=float(ratios[8]),pass_dc_copy_spec=bool(np.max(np.abs(ratios-1))<=.05))


def run(design,output,count):
    output.mkdir(parents=True,exist_ok=False)
    netlist=(design/'extracted_rc.spice').read_text()
    pair_off=sample('',output/'control-pair-off',1,False,True)
    pair_on=[sample('',output/f'control-pair-on-{seed}',seed,True,True) for seed in (1,2,3)]
    repeat=sample('',output/'control-pair-repeat',1,True,True)
    off=[sample(netlist,output/f'control-mirror-off-{seed}',seed,False) for seed in (1,2)]
    controls=dict(pair_disabled_ratio=pair_off,pair_enabled_ratios=pair_on,
        same_seed_reproduces=abs(pair_on[0]-repeat)<1e-10,
        enabled_pair_mismatch_visible=any(abs(v-1)>1e-5 for v in pair_on),
        disabled_pair_matches=abs(pair_off-1)<1e-10,
        disabled_mirror_seed_invariant=abs(off[0]['ratio_at_1v']-off[1]['ratio_at_1v'])<1e-10)
    (output/'controls.json').write_text(json.dumps(controls,indent=2))
    if not all(controls[k] for k in ('same_seed_reproduces','enabled_pair_mismatch_visible',
                                    'disabled_pair_matches','disabled_mirror_seed_invariant')):
        raise RuntimeError('Mismatch activation/reproducibility control failed')
    rows=[sample(netlist,output/f'seed-{seed}',seed,True) for seed in range(1000,1000+count)]
    passed=sum(r['pass_dc_copy_spec'] for r in rows)
    # Wilson 95% interval; an exploratory DC pass fraction, not full yield.
    n=count;phat=passed/n;z=1.96;center=(phat+z*z/(2*n))/(1+z*z/n)
    half=z*np.sqrt(phat*(1-phat)/n+z*z/(4*n*n))/(1+z*z/n)
    result=dict(samples=rows,controls=controls,dc_pass_count=passed,sample_count=n,
        dc_pass_fraction=phat,wilson_95_interval=[float(center-half),float(center+half)],
        netlist_sha256=hashlib.sha256(netlist.encode()).hexdigest(),
        corner='tt',temperature_c=27,reference_current_ua=20,production_qualified=False,
        limitations=['TT/27C DC copy specification only; no bandwidth yield',
            'No spatial gradients or process Monte Carlo', 'Open PDK model statistics need foundry validation',
            'Not production yield or silicon validation'])
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='samples'},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--design',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=50);a=p.parse_args()
    if a.samples<2:p.error('At least two samples required')
    run(a.design.resolve(),a.output.resolve(),a.samples)
