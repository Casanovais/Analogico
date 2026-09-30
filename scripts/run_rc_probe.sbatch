#!/bin/bash
#SBATCH --job-name=analog-rc-probe
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:10:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
.venv/bin/python -u rc_probe.py --design "${1:-results/handoff-4071/design}" --output "results/rc-probe-${SLURM_JOB_ID}"
