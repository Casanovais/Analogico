#!/bin/bash
#SBATCH --job-name=analog-robust-data
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=2
#SBATCH --mem=6G
#SBATCH --time=00:25:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
.venv/bin/python -u robust_dataset.py --output "results/robust-data-${SLURM_JOB_ID}" --workers "$SLURM_CPUS_PER_TASK"
