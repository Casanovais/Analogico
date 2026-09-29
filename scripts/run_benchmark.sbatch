#!/bin/bash
#SBATCH --job-name=analog-benchmark
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:25:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -u -m unittest discover -s tests -v
python -u benchmark.py --output "results/benchmark-${SLURM_JOB_ID}"
