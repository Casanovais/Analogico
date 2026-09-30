"""Generate a small measured SKY130 dataset; retain failures and raw evidence."""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
from mirror_search import evaluate
from physical_flow import ROOT, PDK_BUILD


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    spec = json.loads((ROOT/'examples/mirror_spec.json').read_text())
    pdk = ROOT/'pdks/sky130A'
    os.environ.update(PDK_ROOT=str(pdk.parent), PDKPATH=str(pdk))
    rows = []
    configs = list(itertools.product([1, 2, 4], [0.5, 1, 1.5, 2], [2]))
    for current in (10, 20, 30):
        local = dict(spec, reference_current_ua=current)
        for index, config in enumerate(configs):
            folder = output/f'current-{current}/candidate-{index:03d}'
            result = evaluate(config, local, folder, pdk)
            rows.append(dict(candidate=index, reference_ua=current,
                split='test' if current == 30 else 'train', **result,
                evidence=str(folder.relative_to(output)),
                gds_sha256=hashlib.sha256((folder/'layout.gds').read_bytes()).hexdigest()))
            (output/'rows.json').write_text(json.dumps(rows, indent=2, allow_nan=False)+'\n')
    provenance = dict(schema_version=1, pdk_build=PDK_BUILD, configs=configs,
        specification=spec, source_sha256={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest()
            for n in ('verified_dataset.py','mirror_search.py','physical_flow.py')},
        scope='One upstream current-mirror topology; capacitance-only extraction; no mismatch or foundry signoff',
        split='10/20 uA training; 30 uA held out. Same geometry grid and topology; no cross-topology generalization.')
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(f'Completed {len(rows)} measured cases',flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    run(p.parse_args().output.resolve())
