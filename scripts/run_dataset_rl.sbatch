#!/bin/bash
#SBATCH --job-name=analog-dataset-rl
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
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
run_root="results/dataset-rl-${SLURM_JOB_ID}"
.venv/bin/python -u verified_dataset.py --output "$run_root/data"
python -u rl_search.py --dataset "$run_root/data" --output "$run_root/rl"
python -u -m unittest discover -s tests -v
