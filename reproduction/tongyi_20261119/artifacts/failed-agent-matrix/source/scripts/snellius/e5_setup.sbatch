#!/usr/bin/env bash
#SBATCH --job-name=lrat-e5-setup
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=14G
#SBATCH --time=01:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/env.sh"
: "${TMPDIR:?Snellius job scratch is required}"
srun python "$LRAT_REPO_ROOT/scripts/snellius/check_e5.py"
srun python "$LRAT_REPO_ROOT/scripts/snellius/e5_prepare.py"
