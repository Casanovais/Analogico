"""Experimental detailed-resistance extraction; never a signoff claim."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from physical_flow import ROOT, command, simulate, mirror_instance


def run(design, output):
    design=design.resolve();output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    pdk=ROOT/'pdks/sky130A'
    os.environ.update(PDK_ROOT=str(pdk.parent),PDKPATH=str(pdk))
    script=f'''gds read {{{design/'layout.gds'}}}
load CMIRROR
select top cell
extresist threshold 0
extresist minres 0
extresist mindelay 0
extract do resistance
extract all
ext2spice lvs
ext2spice subcircuit top on
ext2spice extresist on
ext2spice cthresh 0
ext2spice rthresh 0
ext2spice -o {{{output/'extracted_rc.spice'}}}
quit -noprompt
'''
    (output/'extract.tcl').write_text(script)
    log_text = command([ROOT/'tools/bin/magic','-rcfile',pdk/'libs.tech/magic/sky130A.magicrc','-noconsole','-dnull'],
            output,output/'magic.log',input_text=script)
    netlist=(output/'extracted_rc.spice').read_text()
    resistors=re.findall(r'^R\S+\s+\S+\s+\S+\s+([-+\d.eE]+)',netlist,re.M|re.I)
    capacitors=re.findall(r'^C\S+\s+\S+\s+\S+\s+([-+\d.eE]+)',netlist,re.M|re.I)
    emitted=re.search(r'Nets output: (\d+)',log_text)
    total=re.search(r'Total Nets: (\d+)',log_text)
    coverage=bool(emitted and total and int(emitted.group(1))==int(total.group(1))==4)
    evidence=dict(all_four_nets_emitted=coverage,layout_sha256=hashlib.sha256((design/'layout.gds').read_bytes()).hexdigest(),
        resistor_count=len(resistors),capacitor_count=len(capacitors),
        experimental=True,production_qualified=False,electrical=[])
    (output/'summary.json').write_text(json.dumps(evidence,indent=2))
    if not coverage or not resistors or not capacitors:
        raise RuntimeError('Detailed extraction did not emit both resistance and capacitance')
    mirror_instance(netlist)
    for corner in ('tt','ss','ff'):
        for temperature in (-20,27,85):
            metrics=simulate(netlist,output/f'{corner}-{temperature}',pdk,corner,temperature)
            evidence['electrical'].append(metrics)
    evidence['limitations']=['No comparison with a signoff extraction engine',
        'Resistance extraction topology/device-parameter consistency needs independent validation',
        'No mismatch or silicon validation']
    (output/'summary.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--design',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.design,a.output)
