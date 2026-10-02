"""Executable two-stage SKY130 OTA generation, verification and characterization.

Upstream GLayout device/routing generator; open checks are not foundry signoff.
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
import numpy as np
from physical_flow import ROOT, PDK_BUILD, command
from differential_probe import verify_pair

TOP='OPAMP_TWO_STAGE'


def instance(netlist,follower=False):
    match=re.search(r'^\.subckt\s+OPAMP_TWO_STAGE\s+([^\n]+)',netlist,re.M|re.I)
    if not match:raise ValueError('Missing OTA top declaration')
    mapping={'VDD':'VDD','GND':'0','DIFFPAIR_BIAS':'IB1','VP':'VOUT' if follower else 'VN',
             'VN':'VP','CS_BIAS':'IB2','VOUT':'VOUT'}
    pins=match.group(1).split()
    if len(pins)!=len(mapping) or {p.upper() for p in pins}!=set(mapping):raise ValueError('Unexpected OTA pins')
    return 'XOTA '+' '.join(mapping[p.upper()] for p in pins)+' '+TOP


def ac_metrics(data):
    if data.ndim!=2 or data.shape[1]!=3 or not np.all(np.isfinite(data)):
        raise ValueError('Invalid AC table')
    frequency=data[:,0];transfer=data[:,1]+1j*data[:,2]
    if np.any(frequency<=0) or np.any(np.diff(frequency)<=0):raise ValueError('Invalid frequency axis')
    magnitude=np.abs(transfer)
    if magnitude[0]<=0:raise ValueError('Zero AC gain')
    phases=np.unwrap(np.angle(transfer))*180/np.pi
    crosses=np.flatnonzero((magnitude[:-1]>1)&(magnitude[1:]<=1))
    unity=margin=None
    positive_polarity=bool(abs(phases[0])<90)
    if len(crosses):
        i=int(crosses[0]);fraction=-math.log(magnitude[i])/(math.log(magnitude[i+1])-math.log(magnitude[i]))
        unity=float(math.exp(math.log(frequency[i])+fraction*math.log(frequency[i+1]/frequency[i])))
        margin=float(180+phases[i]+fraction*(phases[i+1]-phases[i])) if positive_polarity else None
    return dict(low_frequency_gain_db=float(20*np.log10(magnitude[0])),unity_gain_hz=unity,
                phase_margin_deg=margin,positive_low_frequency_polarity=positive_polarity,
                downward_unity_crossings=len(crosses))


def generate(output,spec):
    from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk
    from glayout.cells.composite.opamp.opamp import opamp
    import gdstk
    pdk.glayers['active_tap']=(65,44)
    parameters={k:tuple(v) if isinstance(v,list) else v for k,v in spec['generator'].items()}
    if parameters.get('add_output_stage') is not False:raise ValueError('This flow supports the two-stage OTA without output buffer')
    cell=opamp(pdk,**parameters)
    netlist=cell.info['netlist'].generate_netlist();instance(netlist)
    (output/'schematic.upstream.spice').write_text(netlist+'\n')
    # Explicit, equivalent primitive calls avoid Netgen's nested parameter default issue.
    netlist=re.sub(r'^(X\S+\s+V1\s+V2)\s+MIMCap(\s+l=[\d.]+\s+w=[\d.]+)\s*$',
        r'\1 sky130_fd_pr__cap_mim_m3_1\2',netlist,flags=re.M|re.I)
    cell.unlock();cell.name=TOP;cell.write_gds(output/'layout.gds')
    shutil.copyfile(output/'layout.gds',output/'layout.upstream.gds')
    gds=gdstk.read_gds(output/'layout.gds')
    removed=[]
    for c in gds.cells:
        omit=[p for p in c.polygons if (p.layer,p.datatype)==(64,44)]
        if omit:c.remove(*omit)
        for polygon in list(c.polygons):
            if (polygon.layer,polygon.datatype)!=(65,20):continue
            bounds=polygon.bounding_box()
            if min(bounds[1][0]-bounds[0][0],bounds[1][1]-bounds[0][1])>=.15-1e-9:continue
            blocked=any(gdstk.boolean([polygon],c.get_polygons(layer=layer,datatype=datatype),'and',precision=.001)
                        for layer,datatype in ((66,20),(66,44),(67,20),(67,44)))
            if blocked:raise ValueError('Thin diffusion intersects a gate/contact; no safe local adapter')
            removed.append(dict(bbox_um=[list(q) for q in bounds],area_um2=polygon.area()))
            c.remove(polygon)
    if len(gds.top_level())!=1:raise ValueError('Expected one OTA top')
    top=gds.top_level()[0];top.name=TOP;gds.write_gds(output/'layout.gds');top.write_svg(output/'layout.svg')
    (output/'schematic.spice').write_text(netlist+'\n')
    bbox=top.bounding_box()
    return dict(area_um2=float((bbox[1][0]-bbox[0][0])*(bbox[1][1]-bbox[0][1])),
        removed_isolated_diffusion_slivers=removed,reference_adapter='MIMCAP wrapper calls replaced by equivalent explicit primitive calls')


def characterize(netlist,output,pdk,spec,corner,temperature):
    output.mkdir(parents=True,exist_ok=False);models=pdk/'libs.ref/sky130_fd_pr/spice'
    passives=ROOT/'tools/models/sky130-passives/models/r+c'
    (output/'.spiceinit').write_text(f'set ngbehavior=hsa\nset ng_nomodcheck\nset sourcepath = ( . {models} {passives} )\n')
    includes='\n'.join(f'.include "{models/f"sky130_fd_pr__{device}_01v8__{corner}.corner.spice"}"\n.include "{models/f"sky130_fd_pr__{device}_01v8__mismatch.corner.spice"}"' for device in ('nfet','pfet'))
    base=f'''SKY130 two-stage OTA
.include "{passives.parent/'parameters/lod.spice'}"
{includes}
.include "{passives/'res_typical__cap_typical.spice'}"
.include "{passives/'res_typical__cap_typical__lin.spice'}"
.include "{models/'sky130_fd_pr__cap_mim_m3_1.model.spice'}"
.option scale=1e-6
.param mc_mm_switch=0 mc_pr_switch=0
.temp {temperature}
{netlist}
VSUPPLY VDD 0 {spec['supply_v']}
IB1 VDD IB1 {spec['diffpair_bias_ua']}u
IB2 VDD IB2 {spec['common_source_bias_ua']}u
CL VOUT 0 {spec['load_pf']}p
'''
    openloop=base+f'''VPLUS VP 0 {spec['common_mode_v']} ac 1
LBIAS VOUT VN 1e9
CBIAS VN 0 1e9
{instance(netlist)}
.control
set wr_vecnames
set wr_singlescale
op
let power = -v(VDD)*i(VSUPPLY)
wrdata op.dat v(VOUT) v(VN) i(VSUPPLY) power
ac dec 60 1 1g
wrdata ac.dat real(v(VOUT)) imag(v(VOUT))
quit
.endc
.end
'''
    (output/'openloop.spice').write_text(openloop)
    command(['ngspice','-b','openloop.spice'],output,output/'openloop.log')
    op=np.atleast_2d(np.loadtxt(output/'op.dat',skiprows=1))
    if op.shape!=(1,5) or not np.all(np.isfinite(op)):raise ValueError('Invalid OTA operating point')
    metrics=ac_metrics(np.loadtxt(output/'ac.dat',skiprows=1))
    follower=base+f'''VPLUS VP 0 {spec['common_mode_v']}
{instance(netlist,True)}
.control
set wr_vecnames
set wr_singlescale
dc VPLUS 0.3 1.5 0.025
wrdata tracking.dat v(VP) v(VOUT)
quit
.endc
.end
'''
    (output/'follower.spice').write_text(follower)
    command(['ngspice','-b','follower.spice'],output,output/'follower.log')
    dc=np.loadtxt(output/'tracking.dat',skiprows=1)
    if dc.ndim!=2 or dc.shape[1]!=3 or not np.all(np.isfinite(dc)):raise ValueError('Invalid OTA tracking table')
    lo,hi=spec['tracking_input_range_v'];active=(dc[:,1]>=lo-1e-8)&(dc[:,1]<=hi+1e-8)
    if not np.any(active):raise ValueError('Tracking specification outside sweep')
    metrics.update(corner=corner,temperature_c=temperature,power_mw=float(op[0,4]*1000),
        quiescent_output_v=float(op[0,1]),closed_loop_dc_error_mv=float(abs(op[0,1]-spec['common_mode_v'])*1000),
        worst_tracking_error_mv=float(np.max(np.abs(dc[active,1]-dc[active,2]))*1000))
    (output/'metrics.json').write_text(json.dumps(metrics,indent=2,allow_nan=False)+'\n')
    return metrics


def meets(metrics,spec):
    checks=(('low_frequency_gain_db','minimum_gain_db',True),('unity_gain_hz','minimum_unity_gain_hz',True),
            ('phase_margin_deg','minimum_phase_margin_deg',True),('power_mw','maximum_power_mw',False),
            ('worst_tracking_error_mv','maximum_tracking_error_mv',False))
    return metrics.get('positive_low_frequency_polarity') is True and all(
        isinstance(metrics.get(k),(int,float)) and math.isfinite(metrics[k]) and metrics[k]>=0
        and (metrics[k]>=spec[limit] if lower else metrics[k]<=spec[limit]) for k,limit,lower in checks)


def run(args):
    spec=json.loads(args.spec.read_text());output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    pdk=ROOT/'pdks/sky130A';os.environ.update(PDK_ROOT=str(pdk.parent),PDKPATH=str(pdk))
    shutil.copyfile(args.spec,output/'specification.json');(output/'source').mkdir()
    for name in ('ota_flow.py','differential_probe.py','physical_flow.py'):shutil.copyfile(ROOT/name,output/'source'/name)
    if args.design is None:
        geometry=generate(output,spec)
    else:
        prior=args.design.resolve();prior_summary=json.loads((prior/'summary.json').read_text())
        prior_spec=json.loads((prior/'specification.json').read_text())
        if prior_spec['generator']!=spec['generator']:
            raise ValueError('Reused layout generator parameters differ from specification')
        if hashlib.sha256((prior/'layout.gds').read_bytes()).hexdigest()!=prior_summary['layout_sha256']:
            raise ValueError('Reused layout hash differs from prior evidence')
        if not prior_summary['verification']['drc_pass'] or not prior_summary['verification']['lvs_pass']:
            raise ValueError('Reused layout has not passed verification')
        for name in ('layout.gds','layout.svg','schematic.spice','layout.upstream.gds','schematic.upstream.spice'):
            if (prior/name).is_file():shutil.copyfile(prior/name,output/name)
        geometry=prior_summary['geometry']
    verification=verify_pair(output,pdk,TOP)
    summary=dict(input_roles={'logical_noninverting':'native VN','logical_inverting':'native VP'},pdk_build=PDK_BUILD,generator='Upstream GLayout two-stage opamp',geometry=geometry,
        verification=verification,electrical=[],specification_pass=False,production_qualified=False,
        layout_sha256=hashlib.sha256((output/'layout.gds').read_bytes()).hexdigest(),
        passive_provenance=json.loads((ROOT/'tools/models/sky130-passives/provenance.json').read_text()),
        limitations=['Open-tool verification is not foundry signoff','Capacitance-only extraction',
        'No OTA mismatch, noise, slew-rate or silicon validation','Supplemental official passive models use a separately pinned revision'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if not verification['drc_pass'] or not verification['lvs_pass']:
        raise RuntimeError('OTA DRC/LVS failed; raw evidence retained')
    for corner in spec['corners']:
        for temperature in spec['temperatures_c']:
            for source in ('schematic','extracted_capacitance'):
                metrics=characterize((output/f'{source}.spice').read_text(),output/f'{source}-{corner}-{temperature}',pdk,spec,corner,temperature)
                summary['electrical'].append(dict(source=source,meets_specification=meets(metrics,spec),**metrics))
                (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    summary['specification_pass']=all(m['meets_specification'] for m in summary['electrical'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not summary['specification_pass']:raise RuntimeError('OTA does not meet the specified electrical targets')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,default=ROOT/'examples/ota_qualified_spec.json')
    p.add_argument('--design',type=Path,help='Reuse and independently reverify a checked layout with identical generator parameters')
    p.add_argument('--output',type=Path,required=True);run(p.parse_args())
