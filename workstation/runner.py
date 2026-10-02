"""Run local EDA wrappers and validate standardized evidence; Python stdlib only.

Use on the licensed workstation. No network, shell, or automatic report transfer.
Vendor invocation and deck selection are supplied by the local CAD setup.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def evidence_pass(kind, evidence):
    if evidence.get('complete') is not True:
        return False
    if kind == 'drc':
        count=evidence.get('error_count')
        return type(count) is int and count == 0
    if kind == 'lvs':
        return (evidence.get('match') is True and evidence.get('device_parameters_checked') is True
                and type(evidence.get('property_errors')) is int and evidence['property_errors']==0)
    if kind == 'pex':
        return (evidence.get('topology_checked') is True and evidence.get('resistance_extracted') is True
                and evidence.get('capacitance_extracted') is True)
    if kind == 'simulation':
        required=evidence.get('required_conditions');observed=evidence.get('observed_conditions')
        return (isinstance(required,list) and len(required)>0 and all(isinstance(x,str) for x in required)
                and len(set(required))==len(required) and isinstance(observed,list)
                and all(isinstance(x,str) for x in observed) and len(set(observed))==len(observed)
                and set(required)==set(observed) and evidence.get('meets_specification') is True)
    raise ValueError('Unknown evidence kind')


def run(config_path, design_path, output_path):
    config=json.loads(config_path.read_text());design=design_path.resolve();output=output_path.resolve()
    steps=config.get('steps',[])
    if len(steps)!=4 or {step.get('kind') for step in steps}!={'drc','lvs','pex','simulation'}:
        raise ValueError('Exactly one DRC, LVS, PEX and simulation step is required')
    if [s['kind'] for s in steps]!=['drc','lvs','pex','simulation']:
        raise ValueError('Steps must follow DRC, LVS, PEX, simulation order')
    if not (design/'layout.gds').is_file() or not (design/'schematic.spice').is_file():
        raise ValueError('Required design inputs are missing')
    if output==design or design in output.parents or output in design.parents:
        raise ValueError('Keep evidence output separate from design inputs')
    output.mkdir(parents=True,exist_ok=False)
    substitutions={'design':str(design),'output':str(output),
                   'gds':str(design/'layout.gds'),'schematic':str(design/'schematic.spice')}
    results=[]
    for step in steps:
        kind=step['kind'];argv=step.get('argv')
        if not isinstance(argv,list) or not argv or not all(isinstance(a,str) for a in argv):
            raise ValueError('Provide a nonempty argv list; shell commands are unsupported')
        argv=[arg.format_map(substitutions) for arg in argv]
        report=(output/step['report']).resolve()
        if output not in report.parents or report.exists():raise ValueError('Report must be a fresh path inside output')
        timeout=step.get('timeout_seconds',3600)
        if type(timeout) is not int or timeout<=0:raise ValueError('Positive timeout required')
        execution=subprocess.run(argv,cwd=output,text=True,stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT,timeout=timeout,check=False)
        (output/f'{kind}.log').write_text(execution.stdout)
        evidence=json.loads(report.read_text()) if report.is_file() else {}
        passed=execution.returncode==0 and evidence_pass(kind,evidence)
        results.append(dict(kind=kind,returncode=execution.returncode,pass_=passed,
            argv_sha256=hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
            report_sha256=hashlib.sha256(report.read_bytes()).hexdigest() if report.is_file() else None))
        summary=dict(local_flow_pass=all(r['pass_'] for r in results) and len(results)==4,
            foundry_signoff_claim=False,steps=results,
            layout_sha256=hashlib.sha256((design/'layout.gds').read_bytes()).hexdigest())
        (output/'local-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        if not passed:raise RuntimeError(f'{kind} rejected; inspect local evidence in {output}')
    print('Local evidence checks passed. Results remain in',output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--design',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    run(a.config.resolve(),a.design,a.output)
