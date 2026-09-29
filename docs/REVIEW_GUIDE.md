# Review demonstrator guide

This project runs a reproducible SKY130 current-mirror experiment: electrical
specification → Bayesian dimension search → generated/routed GDS → independent
DRC/LVS → capacitance-extracted DC/AC characterization → review report. It also
includes a separate synthetic block-placement learning benchmark.

The physical flow uses the upstream **OpenFASOC / GLayout** transistor and routing
generator. Our contributions are search, experiment orchestration, the local
SKY130 layer adapter, verification gates/negative controls, characterization,
placement-learning experiments and reporting. This is an engineering
demonstrator, not foundry-signed-off IP or a general chip designer.

## Run the complete experiment

The toolchain is installed in this workspace. From the project root:

```bash
source /data/02/up202208591/miniconda3/bin/activate tese_chips
sbatch scripts/run_review.sbatch
squeue -u "$USER"
```

The job requests one CPU, 3 GB RAM and up to 25 minutes in `normal`, with `cpu`
QoS. It runs 13 unit tests, a baseline physical design, deliberate-error
verification controls, a 360-run placement benchmark, 20 paired Bayesian/random
trials and an exhaustive 60-candidate physical grid audit before creating the
report and package.

Outputs under `results/review-<job-id>`:

- `report/index.html`: self-contained visual report.
- `physical/`: baseline GDS, SPICE, DRC/LVS and 18 corner/source simulations.
- `controls/`: wrong widths and narrow metal, with rejection reports.
- `search/designs/`: candidate layouts, checks and nine extracted simulations
  per physically valid candidate.
- `search/summary.json`: best design, search traces and strategy statistics.
- `benchmark/`: frozen placement model, paired CSV, graph previews and hashes.
- `source/`: source snapshot for audit.

The shareable package is `results/review-<job-id>.zip`, with the job output in
`slurm-<job-id>.out`. The best design is the minimum feasible area among the
explicit 60 grid points after auditing the entire grid. This does not imply a
minimum over continuous dimensions or arbitrary circuit topologies.

## Physical specification and methodology

`examples/mirror_spec.json` defines a 20 µA 1:1 NFET mirror, maximum 5% copy error
over 0.6–1.6 V output, maximum 0.9 V reference bias and minimum 10 MHz bandwidth.
Every constraint must hold at TT/SS/FF and −20/27/85°C. Width, length and
interdigitated column count are discrete search variables. The characterization
API fixes this voltage range and rejects a different one rather than silently
measuring the wrong range.

The Bayesian model is a Gaussian process with a fixed RBF kernel. It minimizes
log(layout area) plus penalties for normalized electrical constraint excesses.
Expected improvement selects subsequent candidates using only that trial's
previous observations. Random search shares four initial candidates and the
same query budget. Shared caching saves computation; each lookup still counts
as a design query. The exhaustive audit occurs after all searches. Always read
feasible-design success rates alongside conditional feasible area statistics.

DRC uses Magic's full SKY130 deck. LVS uses an independently extracted netlist
and Netgen's topology/property report, not just its process exit code. Deliberate
incorrect device widths must fail LVS; undersized local interconnect must fail
DRC. Simulation binds each subcircuit's declared pin names because Magic may
reorder the extracted pins.

The downloaded primitive models are flattened; the testbench directly loads
official NFET corner and mismatch-parameter files with Monte Carlo disabled.
The PDK remains unchanged. A local adapter maps substrate ties to GDS 65/44
and omits an unsupported 64/44 p-well annotation. Ordinary SKY130 p-well is
default substrate; see the
[official layer reference](https://skywater-pdk.readthedocs.io/en/main/rules/layers.html).

## Separate placement experiment

The annealer preserves grid spacing, outline, mirror symmetry and centering. A
supervised quadratic move-reward model is trained on separate synthetic graphs,
frozen, and compared with uniform and online adaptive policies. One graph family
is held out entirely. Wire cost uses device centers instead of actual terminals.
The first 360-run experiment generally showed no learning advantage; retain it
as a negative result.

This block benchmark and the real transistor flow are different experiments.
The current mirror uses parameterized interdigitation supplied by GLayout; the
synthetic block policy does not place its individual transistors.

```bash
python -m unittest discover -s tests -v
python analog_layout.py --policy learned --model results/benchmark-4040/move_policy.json
```

## Recreate the physical tools

`tese_chips` supplies Python 3.10, Ngspice 41 and compiler/Tcl/Tk dependencies.
The legacy GLayout stack is isolated in `.venv` so its NumPy constraints do not
alter that conda environment. Sources, builds and the primitive PDK are in this
project under `/data/02`; shared datasets remain unchanged.

```bash
bash scripts/setup_physical.sh
```

Setup installs Python requirements, downloads pinned upstream tool sources and
the PDK primitive library, installs a small header-only dependency and submits
the CPU tool build. Wait for that job to complete before running the review.
`scripts/build_tools.sbatch` records compiler compatibility options.
`requirements-physical.lock.txt` records locally installed Python dependencies;
inherited dependencies come from the existing conda environment.

Pinned PDK build: `7519dfb04400f224f140749cda44ee7de6f5e095`.
Magic commit: `4f53bb3091d1e4a9b2009a58f157a8a4331d4c84`.
Netgen commit: `3cb047bd6b55ae09c8eefeb479b4fe746cfdb948`.

## Evidence boundary

Open DRC/LVS results are not foundry signoff. Remaining work includes
interconnect resistance extraction, mismatch/yield analysis, foundry-specific
antenna/density/latchup coverage, larger circuit families and silicon validation.
No design has been submitted for fabrication. See [review criteria](REVIEW_CRITERIA.md).

Exploratory runs remain under `results/` for audit. Runs marked `INVALIDATED.md`
contain erroneous extracted pin binding and must not be used as electrical
evidence. The final review job regenerates its artifacts with corrected binding.
