"""Unity-follower step response diagnostics from qualified OTA testbenches."""
import argparse
import json
import re
import shutil
from pathlib import Path
import numpy as np
from physical_flow import command


def step_metrics(data):
    if data.ndim!=2 or data.shape[1]!=3 or not np.all(np.isfinite(data)) or np.any(np.diff(data[:,0])<=0):
        raise ValueError('Invalid transient table')
    t,vin,vout=data.T;results=[]
    for start,end,target,direction in ((2.02e-6,7.9e-6,1.,1),(8.02e-6,13.9e-6,.9,-1)):
        mask=(t>=start)&(t<=end);times=t[mask];values=vout[mask]
        if len(times)<10:raise ValueError('Incomplete step interval')
        bad=np.flatnonzero(np.abs(values-target)>.001)
        settled=None if len(bad) and bad[-1]==len(values)-1 else float(times[bad[-1]+1]-start if len(bad) else times[0]-start)
        final_level=float(np.median(values[max(0,len(values)-max(10,len(values)//10)):]))
        final_bad=np.flatnonzero(np.abs(values-final_level)>.001)
        final_settled=None if len(final_bad) and final_bad[-1]==len(values)-1 else float(times[final_bad[-1]+1]-start if len(final_bad) else times[0]-start)
        results.append(dict(direction='rising' if direction==1 else 'falling',
            settling_to_1mv_seconds=settled,overshoot_percent=float(max(0,np.max(direction*(values-target)))/.1*100),
            settling_to_final_level_1mv_seconds=final_settled,final_level_v=final_level,
            final_error_mv=float(abs(values[-1]-target)*1000)))
    return dict(steps=results,maximum_absolute_slew_v_per_us=float(np.max(np.abs(np.diff(vout)/np.diff(t)))*1e-6))


def run(design,output):
    summary=json.loads((design/'summary.json').read_text())
    if not summary['specification_pass']:raise ValueError('Requires a fully passing OTA')
    output.mkdir(parents=True,exist_ok=False);rows=[]
    for row in summary['electrical']:
        name=f"{row['source']}-{row['corner']}-{row['temperature_c']}"
        original=design/name;folder=output/name;folder.mkdir()
        shutil.copyfile(original/'.spiceinit',folder/'.spiceinit')
        deck=(original/'follower.spice').read_text().split('.control')[0]
        deck,count=re.subn(r'^VPLUS VP 0 [^\n]+$',
            'VPLUS VP 0 PWL(0 0.9 2u 0.9 2.02u 1.0 8u 1.0 8.02u 0.9 14u 0.9)',deck,flags=re.M)
        if count!=1:raise ValueError('Expected one input source')
        deck+='''.control
set wr_vecnames
set wr_singlescale
tran 10n 14u
wrdata transient.dat v(VP) v(VOUT)
quit
.endc
.end
'''
        (folder/'transient.spice').write_text(deck)
        command(['ngspice','-b','transient.spice'],folder,folder/'ngspice.log')
        metrics=step_metrics(np.loadtxt(folder/'transient.dat',skiprows=1))
        rows.append(dict(source=row['source'],corner=row['corner'],temperature_c=row['temperature_c'],**metrics))
        (output/'summary.json').write_text(json.dumps(dict(diagnostic_only=True,
            input_step_v=.1,edge_seconds=20e-9,settling_tolerance_v=.001,electrical=rows,
            limitations=['No transient requirement was supplied; results are diagnostic','No noise, PSRR, CMRR, OTA mismatch or silicon validation']),indent=2)+'\n')
    print('Completed',len(rows),'transient conditions',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--design',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.design.resolve(),a.output.resolve())
