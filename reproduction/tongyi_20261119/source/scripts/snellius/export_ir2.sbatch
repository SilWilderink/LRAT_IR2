#!/usr/bin/env bash
#SBATCH --job-name=lrat-export-ir2
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit through Slurm}"
: "${TMPDIR:?Snellius job scratch required}"
export LRAT_REPO_ROOT=/gpfs/home6/scur0901/LRAT
export TMPDIR
srun /usr/bin/python3 "$LRAT_REPO_ROOT/scripts/snellius/export_ir2.py"
