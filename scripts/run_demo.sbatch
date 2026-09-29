#!/bin/bash
#SBATCH --job-name=analog-placement
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from the project root}"
export OMP_NUM_THREADS=1
python -u -m unittest discover -s tests -v
python -u analog_layout.py --steps 10000 --seed 0 --output "results/job-${SLURM_JOB_ID}/adaptive"
python -u analog_layout.py --steps 10000 --seed 0 --policy uniform --output "results/job-${SLURM_JOB_ID}/uniform"
