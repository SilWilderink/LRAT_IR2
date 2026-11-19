#!/usr/bin/env bash
#SBATCH --job-name=lrat-eval-index
#SBATCH --partition=gpu_a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=18
#SBATCH --mem=100G
#SBATCH --time=02:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
srun python "$LRAT_REPO_ROOT/scripts/snellius/eval_index.py"
