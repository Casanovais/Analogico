"""Require LVS to reject deliberately incorrect MIM capacitor dimensions."""
import argparse
import json
import os
import shutil
from pathlib import Path
from differential_probe import verify_pair
from ota_flow import TOP
from physical_flow import ROOT


def run(design,output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(design/'layout.gds',output/'layout.gds')
    original=(design/'schematic.spice').read_text()
    altered=original.replace('sky130_fd_pr__cap_mim_m3_1 l=12.0 w=12.0',
                             'sky130_fd_pr__cap_mim_m3_1 l=12.0 w=15.0')
    if altered==original:raise ValueError('Expected original 12um capacitor reference')
    (output/'schematic.spice').write_text(altered)
    os.environ.update(PDK_ROOT=str(ROOT/'pdks'),PDKPATH=str(ROOT/'pdks/sky130A'))
    result=verify_pair(output,ROOT/'pdks/sky130A',TOP)
    report=(output/'lvs.log').read_text()
    result['negative_control_pass']=result['drc_pass'] and not result['lvs_pass'] and 'Property errors were found' in report
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    if not result['negative_control_pass']:raise RuntimeError('LVS did not reject wrong capacitor dimensions')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--design',type=Path,default=ROOT/'results/ota-4088')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();run(a.design,a.output)
