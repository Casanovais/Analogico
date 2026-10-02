"""Schematic-only compensation screening; candidates require fresh layout verification."""
import argparse
import copy
import itertools
import json
import re
from pathlib import Path
from ota_flow import characterize, meets
from physical_flow import ROOT


def run(output,design):
    output.mkdir(parents=True, exist_ok=False)
    spec=json.loads((ROOT/'examples/ota_spec.json').read_text())
    netlist=(design/'schematic.spice').read_text()
    results=[]
    for index,(size,dp,cs) in enumerate(itertools.product((18,24,32,40),(10,20,30),(5,10,20))):
        local=copy.deepcopy(spec)
        local['generator']['mim_cap_size']=[size,size]
        local['diffpair_bias_ua']=dp;local['common_source_bias_ua']=cs
        modified,count=re.subn(r'(sky130_fd_pr__cap_mim_m3_1 l=)12\.0 w=12\.0',rf'\g<1>{size}.0 w={size}.0',netlist)
        if count!=6:raise ValueError('Expected six explicit compensation capacitors')
        folder=output/f'candidate-{index:03d}'
        metrics=characterize(modified,folder,ROOT/'pdks/sky130A',local,'tt',27)
        (folder/'specification.json').write_text(json.dumps(local,indent=2)+'\n')
        row=dict(index=index,size_um=size,diffpair_bias_ua=dp,common_source_bias_ua=cs,
                 nominal_pass=meets(metrics,local),metrics=metrics)
        results.append(row)
        (output/'summary.json').write_text(json.dumps(dict(schematic_only=True,candidates=results),indent=2)+'\n')
        print(json.dumps(row),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--design',type=Path,default=ROOT/'results/ota-4088')
    args=parser.parse_args();run(args.output,args.design)
