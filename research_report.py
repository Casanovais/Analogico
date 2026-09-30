"""Package measured dataset, RL, RC and mismatch evidence into a review artifact."""
import argparse
import csv
import hashlib
import html
import json
import shutil
from pathlib import Path


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    inputs={'dataset':args.dataset,'rl':args.rl,'rc-small':args.rc_small,'rc-large':args.rc_large,
            'mismatch-small':args.mismatch_small,'mismatch-large':args.mismatch_large,'data-audit':args.audit}
    for name,path in inputs.items(): shutil.copytree(path,output/name)
    (output/'source').mkdir()
    for name in ('verified_dataset.py','rl_search.py','audit_osiris.py','rc_probe.py','mismatch_probe.py',
                 'physical_flow.py','mirror_search.py','research_report.py'):
        shutil.copyfile(Path(__file__).resolve().parent/name,output/'source'/name)
    shutil.copytree(Path(__file__).resolve().parent/'scripts',output/'source/scripts')
    shutil.copytree(Path(__file__).resolve().parent/'tests',output/'source/tests')
    shutil.copyfile(Path(__file__).resolve().parent/'docs/DATA_AND_RL.md',output/'METHODS.md')
    data=json.loads((output/'dataset/rows.json').read_text())
    rl=json.loads((output/'rl/report.json').read_text())
    if hashlib.sha256((output/'dataset/rows.json').read_bytes()).hexdigest()!=rl['dataset_sha256']:
        raise ValueError('RL report refers to another dataset')
    if hashlib.sha256((output/'source/rl_search.py').read_bytes()).hexdigest()!=rl['source_sha256']:
        raise ValueError('RL source snapshot differs from the experiment')
    small=json.loads((output/'mismatch-small/summary.json').read_text())
    large=json.loads((output/'mismatch-large/summary.json').read_text())
    with (output/'measured_cases.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['current_ua','candidate','width_um','length_um','columns','area_um2','worst_error_percent','split'])
        for row in data:
            writer.writerow([row['reference_ua'],row['candidate'],*row['config'],row['geometry']['area_um2'],row['worst_error_percent'],row['split']])
    # Standalone scientific plot plus embedding in the review page.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,4.5))
    for current in (10,20,30):
        rows=[r for r in data if r['reference_ua']==current]
        ax.scatter([r['geometry']['area_um2'] for r in rows],[r['worst_error_percent'] for r in rows],label=f'{current} µA')
    ax.axhline(5,color='black',linestyle='--',label='Original copy-error limit')
    ax.set(xlabel='Layout bounding-box area (µm²)',ylabel='Worst copy error across 9 conditions (%)',
           title='Measured current-mirror pilot: capacitance-only extraction')
    ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(output/'tradeoffs.png',dpi=160);plt.close(fig)
    table=''.join(f'<tr><td>{html.escape(strategy)}</td><td>{s["successful_trials"]}/{s["trials"]}</td><td>{s["mean_best_score"]:.5f}</td></tr>' for strategy,s in rl['summary'].items())
    mismatch_table=''.join(f'<tr><td>{name}</td><td>{s["dc_pass_count"]}/{s["sample_count"]}</td><td>{100*s["wilson_95_interval"][0]:.1f}–{100*s["wilson_95_interval"][1]:.1f}%</td></tr>' for name,s in [('W=2, L=1.5 µm',small),('W=4, L=2 µm',large)])
    page=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Analog data and RL review</title>
<style>body{{font:17px system-ui;max-width:950px;margin:40px auto;padding:0 20px;color:#172433}}table{{border-collapse:collapse}}td,th{{padding:10px;border:1px solid #bbb}}img{{max-width:100%}}.notice{{background:#fff1d2;padding:16px}}</style>
<h1>Verified synthetic data and RL pilot</h1>
<p class="notice">Research evidence. Production qualification remains false. External datasets were audited, not used for training.</p>
<p>12 mirror geometries × 3 reference currents = 36 measured cases, with 324 corner/temperature simulations. Training uses 10/20 µA; 30 µA is held out. This is one upstream GLayout topology.</p>
<img src="tradeoffs.png" alt="Measured area versus worst copy error at three reference currents">
<h2>Sequential sizing/search with reinforcement learning</h2>
<p>REINFORCE, two 64-unit hidden layers. Four shared initial designs and eight total evaluation queries. Three training seeds, 1,000 episodes each; 24,000 cached training lookups are additional costs. Fifty evaluation tasks repeat across models.</p>
<table><tr><th>Method</th><th>Successful evaluations</th><th>Mean best score ↓</th></tr>{table}</table>
<p>RL did not beat Bayesian search on average score. Repeated evaluations are correlated; no significance or general chip-design claim is made.</p>
<h2>Detailed RC and seeded mismatch</h2>
<p>The corrected extraction requires all four nets to be emitted and actual R/C devices. Seeded controls demonstrate reproducibility, local mismatch and matching when disabled.</p>
<table><tr><th>Mirror geometry</th><th>DC pass samples</th><th>Wilson 95% interval</th></tr>{mismatch_table}</table>
<p>TT/27°C, 20 µA, 5% copy-error bound over 0.6–1.6 V only. These fractions are not full electrical or production yield. The larger design passes 39 of the same first 50 seeds versus 37 for the smaller design.</p>
<h2>Data audit and next work</h2>
<p>OSIRIS is a relevant SKY130/PPO source. Only bounded archive inventories and small text samples were downloaded. Its dataset directory is approximately 847 MB; the local dataset inventory covers its first 1 MiB. Dataset-license wording needs reconciliation.</p>
<p>Next: cross-check RC against a trusted receiving flow, add broader PVT/statistical and bandwidth coverage, collect multiple verified circuit families, include robustness in optimization, and compare RL against constrained optimizers with training costs visible.</p>
<p>Foundry signoff, commercial-tool integration and silicon measurements remain outstanding.</p>
<p><a href="METHODS.md">Methods and reproduction</a> · <a href="measured_cases.csv">Measured cases CSV</a> · <a href="rl/report.json">RL report and all traces</a> · <a href="mismatch-small/summary.json">Small-design mismatch</a> · <a href="mismatch-large/summary.json">Large-design mismatch</a> · <a href="manifest.json">File checksums</a></p>
</html>'''
    (output/'index.html').write_text(page)
    manifest={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob('*')) if p.is_file()}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Review:',output/'index.html')
    print('Archive:',shutil.make_archive(str(output),'zip',root_dir=output))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','rl','rc-small','rc-large','mismatch-small','mismatch-large','audit','output'):
        p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
