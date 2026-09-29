#!/bin/bash
# Run once from the project root; downloads only into this project/cache.
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
project_root="$PWD"
test -f physical_flow.py
export PIP_CACHE_DIR="$project_root/.cache/pip"
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-physical.txt
mkdir -p tools/src tools/logs
if [ ! -f tools/deps/include/X11/X.h ]; then
    conda create --prefix "$project_root/tools/deps" --override-channels -c conda-forge --no-deps -y xorg-xorgproto=2025.1=hebe6cf0_3
fi
if [ ! -d tools/src/magic/.git ]; then
    git clone --no-checkout https://github.com/RTimothyEdwards/magic.git tools/src/magic
    git -C tools/src/magic checkout --detach 4f53bb3091d1e4a9b2009a58f157a8a4331d4c84
fi
if [ ! -d tools/src/netgen/.git ]; then
    git clone --no-checkout https://github.com/RTimothyEdwards/netgen.git tools/src/netgen
    git -C tools/src/netgen checkout --detach 3cb047bd6b55ae09c8eefeb479b4fe746cfdb948
fi
.venv/bin/volare enable --pdk-root "$project_root/pdks" --pdk sky130 -l sky130_fd_pr 7519dfb04400f224f140749cda44ee7de6f5e095
sbatch scripts/build_tools.sbatch
