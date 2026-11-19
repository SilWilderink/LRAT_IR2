#!/usr/bin/env bash
#SBATCH --job-name=lrat-archive
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/env.sh"
: "${TMPDIR:?Snellius job scratch is required}"
srun python "$LRAT_REPO_ROOT/scripts/snellius/archive_results.py" \
    --destination "${1:?Provide the permanent home destination}"
