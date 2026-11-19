#!/usr/bin/env bash
#SBATCH --partition=gpu_a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:?Frozen source snapshot required}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
: "${TMPDIR:?Snellius job scratch required}"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 VLLM_WORKER_MULTIPROC_METHOD=spawn
export TORCHINDUCTOR_CACHE_DIR="$TMPDIR/lrat-matrix-torchinductor"
export TRITON_CACHE_DIR="$TMPDIR/lrat-matrix-triton"
export TORCH_EXTENSIONS_DIR="$TMPDIR/lrat-matrix-extensions"
srun --ntasks=1 --gpu-bind=none python "$LRAT_REPO_ROOT/scripts/snellius/matrix_stage.py" "$1"
