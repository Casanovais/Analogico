#!/bin/bash
#SBATCH --job-name=analog-eda-tools
#SBATCH --partition=normal
#SBATCH --qos=cpu
#SBATCH --cpus-per-task=2
#SBATCH --mem=2G
#SBATCH --time=00:25:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
source /data/02/up202208591/miniconda3/bin/activate tese_chips
project_root="${SLURM_SUBMIT_DIR:?Submit from project root}"
export LD_LIBRARY_PATH="${CONDA_PREFIX}/lib:${LD_LIBRARY_PATH:-}"
export CPPFLAGS="-I${project_root}/tools/deps/include -I${CONDA_PREFIX}/include"
export LDFLAGS="-L${CONDA_PREFIX}/lib -Wl,-rpath,${CONDA_PREFIX}/lib"
# The conda GCC defaults to C23; upstream tools use C11-era declarations.
export CFLAGS="-O2 -fPIC -std=gnu11"
cd "$project_root/tools/src/magic"
git rev-parse HEAD > "$project_root/tools/logs/magic-commit.txt"
./configure --prefix="$project_root/tools" --without-x --without-opengl --with-tk="${CONDA_PREFIX}/lib" --with-tcl="${CONDA_PREFIX}/lib" --disable-readline > "$project_root/tools/logs/magic-configure.log" 2>&1
make -j "${SLURM_CPUS_PER_TASK}" > "$project_root/tools/logs/magic-build.log" 2>&1
make install > "$project_root/tools/logs/magic-install.log" 2>&1
cd "$project_root/tools/src/netgen"
git rev-parse HEAD > "$project_root/tools/logs/netgen-commit.txt"
export CFLAGS="${CFLAGS} -Wno-error=implicit-function-declaration -I${project_root}/tools/deps/include -I${CONDA_PREFIX}/include"
./configure --prefix="$project_root/tools" --with-x --x-includes="${CONDA_PREFIX}/include" --x-libraries="${CONDA_PREFIX}/lib" --with-tk="${CONDA_PREFIX}/lib" --with-tcl="${CONDA_PREFIX}/lib" > "$project_root/tools/logs/netgen-configure.log" 2>&1
make clean > "$project_root/tools/logs/netgen-clean.log" 2>&1
make -j "${SLURM_CPUS_PER_TASK}" > "$project_root/tools/logs/netgen-build.log" 2>&1
make install > "$project_root/tools/logs/netgen-install.log" 2>&1
"$project_root/tools/bin/magic" --version
test -x "$project_root/tools/bin/netgen"
