"""Fail-closed electrical qualification and portable review handoff packaging."""
import argparse
import hashlib
import itertools
import json
import math
import shutil
from pathlib import Path


def qualify(summary, spec):
    failures = []
    def require(condition, message):
        if not condition:
            failures.append(message)
    require(spec['output_voltage_range_v'] == [0.6, 1.6], 'Unsupported output voltage range')
    verification = summary.get('verification', {})
    require(verification.get('drc_pass') is True and verification.get('drc_error_count') == 0, 'DRC did not pass')
    require(verification.get('lvs_pass') is True, 'LVS did not pass')
    expected = set(itertools.product(('schematic', 'extracted_capacitance'), spec['corners'], spec['temperatures_c']))
    seen = set()
    for row in summary.get('electrical', []):
        key = (row.get('source'), row.get('corner'), row.get('temperature_c'))
        require(key in expected, f'Unexpected simulation {key}')
        require(key not in seen, f'Duplicate simulation {key}')
        seen.add(key)
        require(row.get('reference_ua') == spec['reference_current_ua'], f'Wrong reference current {key}')
        for metric, limit, upper in (
            ('worst_error_percent_0p6_to_1p6v', spec['max_copy_error_percent'], True),
            ('max_reference_voltage_v', spec['max_reference_voltage_v'], True),
            ('bandwidth_3db_hz', spec['minimum_bandwidth_hz'], False),
        ):
            value = row.get(metric)
            # A missing bandwidth is an unqualified measurement, not infinity.
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            require(valid and value >= 0 and (value <= limit if upper else value >= limit), f'{key}: {metric} failed or missing')
    require(seen == expected, 'Missing required source/corner/temperature coverage')
    return {'review_qualified': not failures, 'production_qualified': False,
            'failures': failures, 'expected_simulations': len(expected),
            'observed_simulations': len(summary.get('electrical', [])),
            'outstanding': ['Full interconnect RC extraction', 'Mismatch and yield validation',
                            'Foundry signoff decks and reliability checks',
                            'Commercial-tool import and verification', 'Silicon validation']}


def package(design, specification, output):
    design, output = design.resolve(), output.resolve()
    if output.exists():
        raise ValueError('Use a new output directory to preserve previous handoffs')
    if design == output or design in output.parents or output in design.parents:
        raise ValueError('Handoff and input directories must be separate')
    summary = json.loads((design / 'summary.json').read_text())
    spec = json.loads(specification.read_text())
    result = qualify(summary, spec)
    gds = design / 'layout.gds'
    if hashlib.sha256(gds.read_bytes()).hexdigest() != summary.get('layout_sha256'):
        raise ValueError('Layout hash does not match verified summary')
    source = Path(__file__).resolve().with_name('physical_flow.py')
    if hashlib.sha256(source.read_bytes()).hexdigest() != summary.get('source_sha256'):
        raise ValueError('Physical-flow source no longer matches verified run')
    magic_text = (design / 'magic.log').read_text()
    lvs_text = (design / 'lvs.log').read_text()
    import re
    drc_counts = re.findall(r'^DRC_COUNT=(\d+)\s*$', magic_text, re.M)
    if drc_counts != ['0']:
        raise ValueError('Raw Magic evidence does not show a unique zero-error DRC result')
    if 'Circuits match uniquely.' not in lvs_text or 'Property errors were found' in lvs_text:
        raise ValueError('Raw Netgen evidence does not show an LVS pass')
    required = ('layout.gds', 'layout.svg', 'schematic.spice', 'extracted.spice',
                'extracted_capacitance.spice', 'summary.json', 'magic.log', 'lvs.log', 'netgen.log')
    for name in required:
        if not (design / name).is_file():
            raise ValueError(f'Missing evidence: {name}')
    if not result['review_qualified']:
        raise ValueError('Qualification rejected: ' + '; '.join(result['failures']))
    output.mkdir(parents=True)
    shutil.copytree(design, output / 'evidence')
    shutil.copyfile(specification, output / 'specification.json')
    (output / 'source').mkdir()
    shutil.copyfile(source, output / 'source/physical_flow.py')
    shutil.copyfile(Path(__file__), output / 'source/qualification.py')
    (output / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'IMPORT.md').write_text('''# SKY130 current-mirror handoff

Top cell: CMIRROR. Technology: SKY130A. Pin binding is by the SPICE
subcircuit declaration; extracted pin order may differ from schematic order.

Use evidence/layout.gds for stream import and evidence/schematic.spice as
the reference netlist. GDS contains polygons and labels; it does not recreate
editable PCells, a native schematic, or connectivity-aware layout metadata.
Attach the matching SKY130 technology library and its official layer map.
Do not map these geometries to another process without regeneration.

For Cadence Virtuoso, use the installed release's XStream In interface with
CMIRROR as top cell and a new destination library attached to the SKY130
technology. For Synopsys Custom Compiler, confirm the installed release's
GDS import procedure and technology mapping with the local CAD setup.
No commercial EDA installation was used to validate this package.
Re-run DRC/LVS and extracted simulation in the receiving flow.

qualification.json records the open-flow review gate and unresolved production
requirements. manifest.json hashes every packaged file except itself; these
hashes detect changes, but are not a signature or a foundry approval.
''')
    files = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob('*')) if p.is_file()}
    (output / 'manifest.json').write_text(json.dumps({'schema_version': 1,
        'top_cell': 'CMIRROR', 'technology': summary['technology'],
        'pdk_build': summary['pdk_build'], 'files_sha256': files}, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print('Handoff:', output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', type=Path, required=True)
    parser.add_argument('--spec', type=Path, default=Path('examples/mirror_spec.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.design, args.spec, args.output)
