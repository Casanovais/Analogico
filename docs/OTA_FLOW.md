# Complete OTA flow: measured prototype and commercial qualification path

The initial product use case is a complete amplifier/OTA design flow: explicit
specification, sizing, layout generation, physical verification, extraction,
electrical characterization, and a review package. The executable prototype
uses an upstream GLayout two-stage SKY130 OTA. It supports this topology rather
than arbitrary circuit synthesis. External ideal bias currents remain required.

## Reproduce on the cluster

Activate `source /data/02/up202208591/miniconda3/bin/activate tese_chips`.
Physical generation uses `.venv/bin/python`; model setup and analysis use the
conda environment. Install the bounded pinned supplemental official model files
with `python setup_ota_models.py`. The script retains hashes and license evidence
under `tools/models/sky130-passives`; it does not modify the installed PDK.

```
sbatch scripts/run_ota.sbatch examples/ota_spec.json
sbatch scripts/run_ota_compensation.sbatch results/ota-<baseline-job-id>
sbatch scripts/run_ota.sbatch examples/ota_qualified_spec.json
sbatch scripts/run_ota_dynamic.sbatch results/ota-4103
sbatch scripts/run_ota_negative.sbatch
```

Job IDs in these example paths identify this measured run; substitute the new
IDs when reproducing it. Each job writes `slurm-<job-id>.out`. The compensation
screen modifies schematic capacitor dimensions only, and is explicitly marked
schematic-only. The selected specification must undergo fresh generation and
verification. `ota_search.py` separately compares live nominal Bayesian and
random bias tuning on a fixed checked layout, then qualifies feasible candidates
over both netlist sources and all process/temperature conditions.

## Specification and evidence

The unchanged electrical targets are 1.8 V supply, 2 pF load, gain at least
40 dB, unity-gain frequency at least 5 MHz, phase margin at least 60 degrees,
power at most 1 mW, and follower tracking error at most 20 mV over 0.8–1.1 V.
The tests cover TT/SS/FF at -20/27/85 C on schematic and capacitance-extracted
netlists: 18 source/condition combinations.
These are MOS process corners; passive models remain at their typical corner.
Passive process variation has not been qualified.
The original design failed stability; the failed run and searches remain
available as evidence. Requirements were not
relaxed. Power includes the external ideal bias reference currents.

The regenerated candidate (job 4103, 40um square capacitors, 30uA input-stage
and 5uA common-source reference currents) passes DRC, LVS and all 18 electrical
conditions. Across both sources, measured gain is 82.27–83.45 dB, unity frequency
11.06–14.07 MHz, phase margin 78.10–85.29 degrees, power 0.133–0.134 mW and
worst tracking error 1.72 mV. Its bounding-box area is 37,333 square micrometers.
It is feasible, but its area has not been optimized.

Job 4106 completes 18 transient diagnostics. All rising/falling steps settle
within 1 mV of their measured final level in at most 445 ns. Falling-edge
undershoot reaches 62% for the 20 ns input edge. Static offset prevents settling
within 1 mV of the ideal commanded voltage. These limitations are retained in
the raw evidence; an application with strict overshoot limits needs further
design work. `ota_handoff.py` audits raw AC/DC tables, coverage, layout hash and
physical reports before packaging; it does not call these diagnostics signoff.

The installed upstream topology's native `VN` is the logical noninverting input;
native `VP` is the logical inverting input. The flow maps logical roles explicitly
and rejects unexpected pin lists. It checks DC bias, input tracking, gain,
positive low-frequency polarity, unity crossing and phase margin. A separate
transient diagnostic measures rising/falling 100 mV follower steps, overshoot,
settling to 1 mV and observed slew rate; these have no supplied acceptance target.

Local generator adapters map the active-tap annotation, omit the unsupported
pwell annotation, remove isolated sub-rule diffusion slivers only if they do not
intersect gate/contact layers, and replace nested MIM wrapper calls with
equivalent explicit primitive calls. Original GDS and SPICE are retained.
Fresh independent DRC/LVS checks follow these changes. The capacitor negative
control deliberately changes 12um reference widths to 15um and requires LVS
property-error rejection while the same physical layout remains DRC-clean.

## Robust synthetic data and RL result

`results/robust-data-4084` contains 20 physically checked mirror geometries at
four bias currents (80 cases), 720 detailed-RC corner/temperature simulations,
and 2,400 seeded TT/27 C mismatch samples. Those samples estimate an empirical
90th-percentile copy error, not production yield. Ten and twenty microamps are
training conditions, fifteen is validation, and thirty is held out for testing.
This tests transfer to a new operating current within one topology, not to
unseen circuit families. Exact source snapshots and measurement provenance
remain with the dataset.

The measured-table replay benchmark uses six queries, shared initial queries,
100 goals and three policy seeds. Three 10,000-episode attention PPO runs were
selected using validation only. Job 4090 produced:

| Method | Feasible trials / 300 | Mean estimated cached-oracle seconds |
| --- | ---: | ---: |
| Attention PPO | 252 | 43.09 |
| Bayesian optimization | 282 | 36.56 |
| Random search | 273 | 38.11 |
| Transferred polynomial surrogate | 288 | 33.17 |

The hybrid selected pure PPO on validation and obtained the same test outcome.
The earlier MLP PPO run achieved 236/300. More policy complexity and training did
not establish an RL economic advantage. A transferred surrogate reduced the
estimated cached-oracle cost by 9.3%; conservative amortization of labels and
the entire benchmark's compute gives approximately 450 repeated tasks to repay
that cost. This estimate excludes engineering, licenses and customer costs,
reuses geometry, and concerns a small mirror benchmark. It is not an OTA or
customer ROI estimate. Trials sharing goals and geometry are correlated.

Published [RoSE](https://github.com/xz-group/RoSE) combines Bayesian optimization
and RL; it is a useful research comparator, not proof of superiority here. Its
GPL-3.0 code has not been copied into this project. Public
[ALIGN](https://github.com/ALIGN-analoglayout/ALIGN-public) examples are additional
candidate circuit sources. The earlier bounded public-data audit is documented
in [DATA_AND_RL.md](DATA_AND_RL.md); no external corpus is treated as independently
verified training ground truth.

## Economic value and licensed tools

The measurable product hypothesis is less engineer time and fewer expensive
verification/simulation cycles to reach an accepted OTA specification. Benchmark
wall time to a fully verified solution, first-pass acceptance, human corrections,
and setup/label costs on held-out OTA design briefs against an engineer and
Bayesian optimization. Retain simpler optimization as the default until learned
policies improve this end-to-end result. Large GPUs do not remove deficiencies
in topology coverage, rewards, models or independent verification.

The [local workstation runner](../workstation/README.md) executes the licensed
DRC/LVS/PEX/simulation wrappers on the separate computer. Its configuration uses
explicit argument vectors and fresh local evidence. The workstation CAD setup
must provide version-specific vendor wrappers, technology mapping and approved
decks. This integration interface has unit tests, but has not been exercised
with Cadence or Synopsys. It does not transfer files automatically. Proprietary
PDKs, models, decks and reports can remain on that computer.

Production gaps include full OTA RC extraction, statistical mismatch/yield,
noise, PSRR/CMRR, application-specific dynamic targets, internal bias generation,
multiple topology families, foundry signoff and silicon correlation. Open-tool
DRC/LVS and model simulations do not establish an industry-qualified product.
