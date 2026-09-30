# Learning-assisted analog automation

The project now includes a real SKY130 current-mirror flow: specification →
Bayesian dimension search → generated/routed GDS → independent DRC/LVS →
capacitance-extracted DC/AC characterization → a shareable visual report.

From the project root, activate `tese_chips` and run:

```bash
sbatch scripts/run_review.sbatch
```

This runs tests, a baseline physical design, deliberate-error verification
controls, a 360-run synthetic placement benchmark, 20 paired Bayesian/random
search trials, and an exhaustive 60-candidate physical grid audit. Results go
to `results/review-<job-id>/report/index.html`, with raw evidence and source in
`results/review-<job-id>.zip`. The job log is `slurm-<job-id>.out`.

Device generation and routing are supplied by **OpenFASOC / GLayout**. This
project contributes learning experiments, search orchestration, the local SKY130
mapping adapter, checks, characterization and reporting. It is an engineering
demonstrator; foundry signoff and silicon validation remain outstanding.

See [the complete review guide](docs/REVIEW_GUIDE.md) for specification, tools,
reproduction instructions, methodology, attribution and limitations.

## Initial block-placement baseline

A small executable experiment for automatic analog **block placement**. It uses
simulated annealing and an epsilon-greedy bandit that learns which move distances
produce improvements. A uniform move policy provides a comparison baseline.
This is a lightweight learning component, not a trained neural chip designer.

The example contains a differential pair, mirrored loads, and a centered tail
device. Every accepted placement satisfies boundary, rectangular spacing,
vertical mirror symmetry, and centering constraints. The objective is weighted
half-perimeter wire length using device centers as terminal proxies. Dimensions
are abstract grid units. There is no routing, PDK, transistor generator,
parasitic extraction, DRC, or LVS; outputs are not fabrication-ready.

## Run on the cluster

From `/data/02/up202208591/Analogico2`:

```bash
source /data/02/up202208591/miniconda3/bin/activate tese_chips
sbatch scripts/run_demo.sbatch
squeue -u "$USER"
```

The job requests one CPU, 1 GB RAM, and five minutes in `normal` with `cpu` QoS. It runs tests
and both policies. Output appears in `slurm-<job-id>.out`; results are saved in
`results/job-<job-id>/{adaptive,uniform}`. Each folder includes initial and
optimized SVG previews, metrics/history in `result.json`, and a reusable
`placement.json` input. No packages, models, or datasets are downloaded.

For a local smoke run:

```bash
python -m unittest discover -s tests -v
python analog_layout.py --seed 0 --steps 10000
```

## Input and interpretation

See `examples/differential_pair.json`: integer boundary and geometry, nonnegative
spacing, unique device names, disjoint symmetry pairs, centered devices, and
weighted nets. Input must start from a legal placement; the optimizer rejects
invalid inputs rather than attempting legalization. Mirror pairs require equal
dimensions. All geometry remains on the integer grid.

Cost improvement demonstrates optimization on this example only. Compare
policies over many seeds and held-out circuits before claiming a learning
advantage. The move policy learns during each run; it is not transferred between
circuits. Reward estimates are saved for inspection. The fixed outline is not
optimized, and matching beyond symmetry (such as common-centroid placement) is
not implemented.

Next research steps: choose a target PDK and circuit family, add pin-aware
placement and routing, integrate actual DRC/LVS and simulation, then train and
evaluate a placement policy against this baseline. Keep generated artifacts
under this project in `/data/02` and shared datasets unchanged in `/data/db`.

## Qualified review handoff

`sbatch scripts/run_handoff.sbatch` regenerates the smallest passing design from
review 4057 (W=2 µm, L=1.5 µm, two columns), runs the test suite and 18
schematic/capacitance-extracted simulations, and builds a handoff under
`results/handoff-<job-id>/package`. `qualification.py` rejects missing or duplicate
corner coverage, nonfinite/missing measurements, specification violations,
failed physical checks, inconsistent raw verification logs and changed layout
or generator-source hashes. The package includes source and file checksums.

This is a review-qualified SKY130 current mirror. Commercial-tool import,
full RC extraction, mismatch/yield and foundry signoff remain outstanding.
See [commercial integration and model scope](docs/COMMERCIAL_INTEGRATION.md).
