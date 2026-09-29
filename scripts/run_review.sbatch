#!/bin/bash
#SBATCH --job-name=analog-industry-review
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:25:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
cd "${SLURM_SUBMIT_DIR:?Submit from project root}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
review_root="results/review-${SLURM_JOB_ID}"
mkdir -p "$review_root/source"
cp ./*.py README.md requirements-physical.txt "$review_root/source/"
cp -r examples scripts tests docs "$review_root/source/"
python -u -m unittest discover -s tests -v
.venv/bin/python -u physical_flow.py --output "$review_root/physical"
.venv/bin/python -u verification_controls.py --base "$review_root/physical" --output "$review_root/controls"
python -u benchmark.py --output "$review_root/benchmark"
.venv/bin/python -u mirror_search.py --seeds 20 --seed-offset 1000 --exhaustive --output "$review_root/search"
.venv/bin/python -u review_report.py --physical "$review_root/physical" --benchmark "$review_root/benchmark" --search "$review_root/search" --controls "$review_root/controls" --output "$review_root/report"
.venv/bin/python -u -c 'import shutil, sys; root=sys.argv[1]; print(shutil.make_archive(root, "zip", root_dir=root))' "$review_root"
