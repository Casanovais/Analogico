# Commercial integration and model scope

The useful current product scope is a reproducible SKY130 current-mirror
search and review handoff. It does not yet meet production qualification.

Cadence documents XStream In/Out in Virtuoso Layout Design Basics:
https://www.cadence.com/en_US/home/training/all-courses/84460.html
GDS is the geometric interchange boundary. Use the receiving installation's
SKY130 technology library and official layer map, then independently verify
imported geometry, labels, DRC/LVS and electrical behavior. Import does not
restore PCells or a native connectivity-aware layout database.

Synopsys Custom Compiler is the relevant custom analog design environment:
https://www.synopsys.com/implementation-and-signoff/custom-design-platform.html
Its exact import and automation setup must be established against the licensed
release and local PDK. No tested Custom Compiler adapter is claimed here.
Neither virtuoso nor custom_compiler was found on PATH during this milestone;
this does not establish whether the university has licenses elsewhere.

The foundry PDK, licensed verification decks, simulator model compatibility and
local CAD configuration determine actual integration. Existing SKY130 polygons
cannot be reused as another process simply by changing a layer map. Commercial
signoff results are required before describing the handoff as production ready.

## Model evidence

Review 4057 exhaustively checked 60 physical candidates and found five feasible
ones. Its paired 12-query searches found feasible designs in 17/20 Bayesian
trials and 16/20 random trials. Conditional median areas were 204.14 and
226.45 square micrometers respectively. Conditional areas exclude failed trials;
these numbers do not establish a statistically significant advantage.
The best grid design has area 176.6865 square micrometers and worst tested
copy error 4.227585 percent. These are finite-grid, single-circuit results.

The search model is a small Gaussian process; the separate synthetic placement
policy is a quadratic reward model. Neither is a general trained chip designer.
The observed limitations cannot be attributed to model size alone. Training a
larger model first requires sufficiently varied, verified circuits, useful
layout constraints and terminal information, and held-out evaluation against
strong optimizers and experienced designers. The earlier synthetic experiment
showed no general learning advantage and remains part of the evidence.

Slurm advertises nodes with L40S and H100 GPUs. Current SPICE, DRC/LVS and the
60-point Gaussian-process experiment run on CPU; GPU availability alone would
not improve those measurements. A future neural experiment should have a
specific dataset, baseline, train/test split, query budget and success criterion
before consuming GPU time.

## Next production milestones

1. Full RC extraction with comparison to a trusted receiving flow.
2. Foundry-model mismatch/yield analysis and reliability checks.
3. Tested commercial import and independently repeated DRC/LVS/simulation.
4. Multiple analog circuit families and held-out PDK/circuit benchmarks.
5. Experienced layout review and fabrication/silicon validation.

The qualification command intentionally reports production_qualified=false
until these separate requirements have evidence. It rejects unknown bandwidth
rather than interpreting a missing measurement as an infinite bandwidth.
