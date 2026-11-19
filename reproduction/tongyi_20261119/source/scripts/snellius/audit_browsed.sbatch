#!/usr/bin/env bash
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
srun python "$LRAT_REPO_ROOT/scripts/snellius/audit_browsed.py" --output "$LRAT_AUDIT_ROOT" --archive "$LRAT_AUDIT_ARCHIVE"
