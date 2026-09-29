# Review milestone

The intended deliverable is a reproducible analog automation demonstrator that
an industry engineer can evaluate. This is distinct from a tapeout-ready IP
claim or a claim that a general AI can autonomously design arbitrary chips.

## Evidence required

1. An explicit circuit/technology scope and measurable specifications.
2. Real generated GDS, independently checked with a pinned PDK and open tools.
3. Layout-versus-schematic evidence including device parameters, not just a
   successful process exit code.
4. Schematic and extracted-layout simulation over process and temperature.
5. A learning experiment compared against non-learning baselines, with
   training/test separation, timing, and all run metrics.
6. A self-contained review report, reproducible cluster scripts, version/hash
   provenance, and clear attribution of existing device generators.

## Current research boundary

The placement benchmark uses synthetic analog-like block graphs, fixed outlines,
device-center terminals, and one held-out graph family. It is not a transistor
layout benchmark. The learning policy is a supervised quadratic reward model,
not a foundation model or reinforcement-learning neural network. The first
360-run experiment generally did not beat either baseline. Keep this result
when presenting subsequent improvements.

The physical demonstrator uses the upstream GLayout SKY130 current-mirror
generator. Its transistor and routing code must be attributed to OpenFASOC.
The project contributes experiment orchestration, learning/benchmark code,
independent verification checks, characterization and reporting. Passing the
implemented flow is not foundry signoff.

Before production use: full interconnect resistance/capacitance extraction,
mismatch/yield analysis, more comprehensive electrical tests, routing/antenna/
density checks appropriate to the foundry flow, and experienced layout review.
Those are outstanding work, not claims covered by the current experiment.

Sources:

- [OpenFASOC / GLayout](https://github.com/idea-fasoc/OpenFASOC)
- [SkyWater open PDK](https://github.com/google/skywater-pdk)
- [Volare](https://github.com/chipfoundry/volare)
- [Magic](https://github.com/RTimothyEdwards/magic)
- [Netgen](https://github.com/RTimothyEdwards/netgen)
