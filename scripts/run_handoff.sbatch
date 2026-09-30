#!/bin/bash
#SBATCH --job-name=analog-handoff
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:10:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
python -u -m unittest discover -s tests -v
handoff_root="results/handoff-${SLURM_JOB_ID}"
.venv/bin/python -u physical_flow.py --width 2 --length 1.5 --columns 2 --output "$handoff_root/design"
python -u qualification.py --design "$handoff_root/design" --output "$handoff_root/package"
