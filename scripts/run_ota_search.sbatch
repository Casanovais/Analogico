#!/bin/bash
#SBATCH --job-name=analog-ota-search
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
run_root="results/ota-search-${SLURM_JOB_ID}"
mkdir -p "$run_root/source"
cp ota_search.py ota_flow.py differential_probe.py physical_flow.py mirror_search.py "$run_root/source/"
.venv/bin/python -u ota_search.py --design "${1:-results/ota-4088}" --output "$run_root/search"
