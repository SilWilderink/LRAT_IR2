#!/usr/bin/env bash
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=02:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
: "${TMPDIR:?Snellius job scratch required}"
srun python "$LRAT_REPO_ROOT/scripts/snellius/matrix_check.py"
srun python "$LRAT_REPO_ROOT/scripts/snellius/matrix_prepare.py"
