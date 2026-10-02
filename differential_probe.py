"""Second-family probe: upstream GLayout differential pair, independent DRC/LVS/DC.

Standalone differential pair with ideal tail current and output-voltage clamps;
this is not a complete OTA or a foundry-signoff result.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import numpy as np
from physical_flow import ROOT, command


def instance(netlist):
    match=re.search(r'^\.subckt\s+DIFF_PAIR\s+([^\n]+)',netlist,re.I|re.M)
    if not match:raise ValueError('Missing differential-pair subcircuit')
    pins=match.group(1).split();mapping={'VP':'VP','VN':'VN','VDD1':'D1','VDD2':'D2','VTAIL':'TAIL','B':'0'}
    if len(pins)!=6 or set(p.upper() for p in pins)!=set(mapping):raise ValueError('Unexpected differential-pair pins')
    return 'XPAIR '+' '.join(mapping[p.upper()] for p in pins)+' DIFF_PAIR'


def generate_pair(output):
    from glayout.pdk.sky130_mapped import sky130_mapped_pdk as pdk
    from glayout.cells.elementary.diff_pair.diff_pair import diff_pair,add_df_labels
    import gdstk
    pdk.glayers['active_tap']=(65,44)
    cell=diff_pair(pdk,width=3,length=1,fingers=2,substrate_tap=True)
    netlist=cell.info['netlist'].generate_netlist()
    cell=add_df_labels(cell,pdk);cell.unlock();cell.name='DIFF_PAIR'
    cell.write_gds(output/'layout.gds')
    gds=gdstk.read_gds(output/'layout.gds')
    for c in gds.cells:
        omit=[p for p in c.polygons if (p.layer,p.datatype)==(64,44)]
        if omit:c.remove(*omit)
    if len(gds.top_level())!=1:raise ValueError('Expected one top')
    top=gds.top_level()[0];top.name='DIFF_PAIR';gds.write_gds(output/'layout.gds');top.write_svg(output/'layout.svg')
    (output/'schematic.spice').write_text(netlist+'\n')
    return netlist


def verify_pair(output,pdk,top="DIFF_PAIR"):
    script=f'''gds read {{{output/'layout.gds'}}}
load {top}
select top cell
drc on
drc style drc(full)
drc check
drc catchup
puts "DRC_COUNT=[drc list count total]"
puts "DRC_DETAILS=[drc listall why]"
drc off
extract all
ext2spice lvs
ext2spice subcircuit top on
ext2spice -o {{{output/'extracted.spice'}}}
ext2spice cthresh 0
ext2spice -o {{{output/'extracted_capacitance.spice'}}}
quit -noprompt
'''
    (output/'verify.tcl').write_text(script)
    text=command([ROOT/'tools/bin/magic','-rcfile',pdk/'libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],output,output/'magic.log',input_text=script)
    counts=re.findall(r'^DRC_COUNT=(\d+)\s*$',text,re.M)
    if len(counts)!=1:raise ValueError('Missing unique DRC count')
    netgen=ROOT/'tools/bin/netgen';launcher=['bash',netgen] if netgen.read_bytes().startswith(b'#!') else [netgen]
    command(launcher+['-batch','lvs',f'{output/"extracted.spice"} {top}',f'{output/"schematic.spice"} {top}',
        pdk/'libs.tech/netgen/sky130A_setup.tcl',output/'lvs.log','-json'],output,output/'netgen.log')
    report=(output/'lvs.log').read_text()
    return dict(drc_error_count=int(counts[0]),drc_pass=counts[0]=='0',
        lvs_pass='Circuits match uniquely.' in report and 'Property errors were found' not in report)


def characterize(netlist,output,pdk,corner,temperature):
    output.mkdir(parents=True,exist_ok=False);models=pdk/'libs.ref/sky130_fd_pr/spice'
    (output/'.spiceinit').write_text(f'set ngbehavior=hsa\nset ng_nomodcheck\nset sourcepath = ( . {models} )\n')
    deck=f'''Differential pair DC probe
.include "{models/f'sky130_fd_pr__nfet_01v8__{corner}.corner.spice'}"
.option scale=1e-6
.param mc_mm_switch=0 mc_pr_switch=0
.include "{models/'sky130_fd_pr__nfet_01v8__mismatch.corner.spice'}"
.temp {temperature}
{netlist}
ITAIL TAIL 0 40u
VD1 D1 0 1.2
VD2 D2 0 1.2
VDIFF DIFF 0 0
BVP VP 0 v=0.8+v(DIFF)/2
BVN VN 0 v=0.8-v(DIFF)/2
{instance(netlist)}
.control
set wr_vecnames
set wr_singlescale
dc VDIFF -0.05 0.05 0.005
wrdata sweep.dat v(DIFF) i(VD1) i(VD2) v(TAIL)
quit
.endc
.end
'''
    (output/'testbench.spice').write_text(deck)
    command(['ngspice','-b','testbench.spice'],output,output/'ngspice.log')
    data=np.loadtxt(output/'sweep.dat',skiprows=1)
    if data.shape!=(21,5) or not np.all(np.isfinite(data)):raise ValueError('Invalid DC sweep')
    d,left,right,tail=data[:,1],-data[:,2],-data[:,3],data[:,4]
    differential=left-right;gm=(differential[11]-differential[9])/.01
    result=dict(corner=corner,temperature_c=temperature,
        balanced_current_error_percent=float(abs(left[10]-right[10])/40e-6*100),
        worst_tail_current_error_percent=float(np.max(np.abs(left+right-40e-6))/40e-6*100),
        differential_transconductance_s=float(gm),minimum_tail_voltage_v=float(tail.min()),
        current_steering_monotonic=bool(np.all(np.diff(differential)>0) or np.all(np.diff(differential)<0)))
    if result['worst_tail_current_error_percent']>.01 or not result['current_steering_monotonic'] or abs(gm)<1e-6:
        raise RuntimeError('Differential-pair functional controls failed')
    (output/'metrics.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def run(output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False);pdk=ROOT/'pdks/sky130A'
    os.environ.update(PDK_ROOT=str(pdk.parent),PDKPATH=str(pdk))
    generate_pair(output);verification=verify_pair(output,pdk)
    summary=dict(verification=verification,electrical=[],generator='Upstream GLayout diff_pair',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitations=['Standalone pair with ideal external bias and drain clamps; not an OTA',
        'Capacitance-only extraction; no mismatch characterization','Not foundry signoff'])
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if not verification['drc_pass'] or not verification['lvs_pass']:raise RuntimeError('Physical checks failed; inspect retained evidence')
    for corner in ('tt','ss','ff'):
        for temperature in (-20,27,85):
            for source in ('schematic','extracted_capacitance'):
                metrics=characterize((output/f'{source}.spice').read_text(),output/f'{source}-{corner}-{temperature}',pdk,corner,temperature)
                summary['electrical'].append(dict(source=source,**metrics))
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output)
