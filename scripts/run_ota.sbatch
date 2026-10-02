#!/bin/bash
#SBATCH --job-name=analog-ota-flow
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
ota_extra=()
if [[ $# -ge 2 ]]; then ota_extra=(--design "$2"); fi
.venv/bin/python -u ota_flow.py --spec "${1:-examples/ota_qualified_spec.json}" --output "results/ota-${SLURM_JOB_ID}" "${ota_extra[@]}"
