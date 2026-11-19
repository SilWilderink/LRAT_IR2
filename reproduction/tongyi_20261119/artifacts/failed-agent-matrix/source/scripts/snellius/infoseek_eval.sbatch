#!/usr/bin/env bash
#SBATCH --job-name=lrat-infoseek-eval
#SBATCH --partition=gpu_a100
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --gpus=4
#SBATCH --cpus-per-task=18
#SBATCH --mem=440G
#SBATCH --time=72:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
: "${TMPDIR:?Snellius job scratch is required}"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 VLLM_WORKER_MULTIPROC_METHOD=spawn
export TORCHINDUCTOR_CACHE_DIR="$TMPDIR/lrat-infoseek-torchinductor"
export TRITON_CACHE_DIR="$TMPDIR/lrat-infoseek-triton"
export TORCH_EXTENSIONS_DIR="$TMPDIR/lrat-infoseek-extensions"
srun --ntasks=4 --cpus-per-task=18 --gpus-per-task=1 --gpu-bind=single:1 \
    python "$LRAT_REPO_ROOT/scripts/snellius/infoseek_index.py" encode
srun --ntasks=1 --cpus-per-task=72 --gpus-per-task=4 --gpu-bind=none \
    python "$LRAT_REPO_ROOT/scripts/snellius/infoseek_index.py" merge
srun --ntasks=1 --cpus-per-task=72 --gpus-per-task=4 --gpu-bind=none \
    python "$LRAT_REPO_ROOT/scripts/snellius/eval_run.py" full
