#!/bin/bash
#SBATCH --job-name=verify-controls
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
.venv/bin/python -u verification_controls.py --base "${CONTROL_BASE:?Export CONTROL_BASE as a verified physical result folder}" --output "results/controls-${SLURM_JOB_ID}"
