# Local licensed-workstation bridge

The commercial tools can stay on the separate licensed computer. This folder
is a vendor-neutral Python runner, not a tested Cadence or Synopsys adapter.
It uses no network and transfers nothing automatically. The CAD administrator
supplies wrappers using that computer's installed versions, technology library,
model files and approved decks. The wrappers and their evidence stay local.

Copy this folder and an appropriate design package to the workstation, set up
`config.example.json` with the local wrapper executables, then run:

```
python runner.py --config local-config.json --design /local/design --output /local/new-evidence
```

The design folder needs `layout.gds` and `schematic.spice`. A technology-specific
import/layer mapping must be established before verification. SKY130 layouts
require the matching technology; a layer-map change does not port a design.
The runner invokes argument vectors without a shell, captures local logs, checks
process status and validates newly produced JSON evidence. It fails on missing
checks or failed stages. It never claims foundry signoff.

Each local wrapper must produce truthful evidence derived from its actual tool
report, with `complete: true` and these additional fields:

- DRC: `error_count: 0`.
- LVS: `match: true`, `device_parameters_checked: true`, `property_errors: 0`.
- PEX: `topology_checked: true`, `resistance_extracted: true`, `capacitance_extracted: true`.
- Simulation: `required_conditions` and `observed_conditions` as unique lists
  of condition identifiers, plus `meets_specification: true` only when every
  specified electrical requirement passes at those conditions.

The required simulation conditions must come from the local project specification,
not merely from whichever simulations happened to run. Retain the vendor reports
and detailed metrics so another engineer can audit the wrapper's interpretation.
Inspect results on that computer. Bring back only information that the applicable
agreement and local data-owner rules permit; this runner does not export it.
