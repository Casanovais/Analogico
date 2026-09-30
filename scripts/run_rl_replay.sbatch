#!/bin/bash
#SBATCH --job-name=analog-rl-replay
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:05:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
replay_root="results/rl-replay-${SLURM_JOB_ID}"
mkdir -p "$replay_root/source"
cp rl_search.py mirror_search.py physical_flow.py verified_dataset.py "$replay_root/source/"
python -u rl_search.py --dataset "${1:-results/dataset-rl-4072/data}" --output "$replay_root/rl"
python -u -m unittest discover -s tests -v
