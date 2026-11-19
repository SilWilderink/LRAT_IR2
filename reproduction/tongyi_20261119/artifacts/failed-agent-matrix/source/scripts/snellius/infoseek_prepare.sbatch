#!/usr/bin/env bash
#SBATCH --job-name=lrat-infoseek-setup
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
: "${TMPDIR:?Snellius job scratch is required}"
srun python "$LRAT_REPO_ROOT/scripts/snellius/infoseek_check.py"
srun python "$LRAT_REPO_ROOT/scripts/snellius/infoseek_prepare.py"
