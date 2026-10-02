"""Audit raw OTA evidence and package the measured design for review."""
import argparse
import hashlib
import itertools
import json
import re
import shutil
from pathlib import Path
import numpy as np
from ota_flow import ac_metrics, meets
from physical_flow import ROOT


def audit(design):
    summary=json.loads((design/'summary.json').read_text())
    spec=json.loads((design/'specification.json').read_text())
    if not summary['specification_pass']:raise ValueError('OTA specification failed')
    if hashlib.sha256((design/'layout.gds').read_bytes()).hexdigest()!=summary['layout_sha256']:
        raise ValueError('Layout hash mismatch')
    counts=re.findall(r'^DRC_COUNT=(\d+)\s*$',(design/'magic.log').read_text(),re.M)
    lvs=(design/'lvs.log').read_text()
    if counts!=['0'] or 'Circuits match uniquely.' not in lvs or 'Property errors were found' in lvs:
        raise ValueError('Raw physical verification failed')
    expected=set(itertools.product(('schematic','extracted_capacitance'),spec['corners'],spec['temperatures_c']))
    keys=[(r['source'],r['corner'],r['temperature_c']) for r in summary['electrical']]
    if len(keys)!=len(expected) or set(keys)!=expected:raise ValueError('Incomplete or duplicate corner coverage')
    for row in summary['electrical']:
        folder=design/f"{row['source']}-{row['corner']}-{row['temperature_c']}"
        raw=ac_metrics(np.loadtxt(folder/'ac.dat',skiprows=1))
        op=np.atleast_2d(np.loadtxt(folder/'op.dat',skiprows=1))
        dc=np.loadtxt(folder/'tracking.dat',skiprows=1)
        if op.shape!=(1,5) or dc.ndim!=2 or dc.shape[1]!=3 or not np.all(np.isfinite(op)) or not np.all(np.isfinite(dc)):
            raise ValueError('Invalid raw measurement table')
        lo,hi=spec['tracking_input_range_v'];mask=(dc[:,1]>=lo-1e-8)&(dc[:,1]<=hi+1e-8)
        if not mask.any():raise ValueError('Missing tracking range')
        raw.update(power_mw=float(op[0,4]*1000),worst_tracking_error_mv=float(np.max(np.abs(dc[mask,1]-dc[mask,2]))*1000))
        if not meets(raw,spec):raise ValueError('Raw electrical target failed')
        for name in ('low_frequency_gain_db','unity_gain_hz','phase_margin_deg','power_mw','worst_tracking_error_mv'):
            if not np.isclose(raw[name],row[name],rtol=1e-10,atol=1e-10):raise ValueError('Reported metric differs from raw table')
    return summary


def run(design,dynamic,output):
    summary=audit(design)
    diagnostic=json.loads((dynamic/'summary.json').read_text())
    if len(diagnostic['electrical'])!=len(summary['electrical']):raise ValueError('Incomplete dynamic coverage')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copytree(design,output/'ota')
    shutil.copytree(dynamic,output/'transient')
    shutil.copytree(ROOT/'results/ota-negative-4104',output/'negative-control')
    shutil.copytree(ROOT/'workstation',output/'workstation',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'results/robust-rl-4090',output/'robust-rl')
    shutil.copytree(ROOT/'results/robust-data-4084',output/'robust-data')
    (output/'source').mkdir()
    for path in ROOT.glob('*.py'):
        shutil.copyfile(path,output/'source'/path.name)
    shutil.copytree(ROOT/'examples',output/'examples')
    shutil.copytree(ROOT/'docs',output/'docs')
    for path in ROOT.glob('requirements*.txt'):shutil.copyfile(path,output/path.name)
    shutil.copytree(ROOT/'scripts',output/'scripts')
    shutil.copytree(ROOT/'tests',output/'tests',ignore=shutil.ignore_patterns('__pycache__'))
    (output/'README.md').write_text('# Measured OTA review package\n\nSee [flow and limitations](docs/OTA_FLOW.md).\n\nThe ota/ folder passed raw-table audit and contains layout, schematic, verification and all 18 electrical conditions. transient/ holds diagnostics, including large falling-edge undershoot. robust-data/ and robust-rl/ are a separate mirror benchmark; they do not establish OTA RL performance. The workstation/ runner needs local vendor wrappers. sha256.json covers every packaged file.\n')
    shutil.copyfile(ROOT/'docs/DATA_AND_RL.md',output/'DATA_AND_RL.md')
    manifest={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()}
    (output/'sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=shutil.make_archive(str(output),'zip',root_dir=output.parent,base_dir=output.name)
    print(archive,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--design',type=Path,required=True)
    p.add_argument('--dynamic',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.design.resolve(),a.dynamic.resolve(),a.output.resolve())
