#!/usr/bin/env bash
#SBATCH --job-name=lrat-eval-pilot
#SBATCH --partition=gpu_a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=4
#SBATCH --cpus-per-task=72
#SBATCH --mem=440G
#SBATCH --time=02:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export TORCHINDUCTOR_CACHE_DIR="$TMPDIR/lrat-eval-torchinductor"
export TRITON_CACHE_DIR="$TMPDIR/lrat-eval-triton"
export TORCH_EXTENSIONS_DIR="$TMPDIR/lrat-eval-extensions"
srun python "$LRAT_REPO_ROOT/scripts/snellius/eval_run.py" "${1:-pilot}"
