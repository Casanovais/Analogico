#!/bin/bash
#SBATCH --job-name=analog-robust-ppo
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
run_root="results/robust-rl-${SLURM_JOB_ID}"
mkdir -p "$run_root/source"
cp robust_rl.py rl_search.py mirror_search.py physical_flow.py "$run_root/source/"
python -u robust_rl.py --dataset "${1:?Measured robust dataset directory required}" --output "$run_root/rl" --architecture "${2:-mlp}" --episodes "${3:-2500}"
python -u -m unittest discover -s tests -v
