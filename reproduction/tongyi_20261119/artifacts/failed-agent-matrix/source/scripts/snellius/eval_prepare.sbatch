#!/usr/bin/env bash
#SBATCH --job-name=lrat-eval-setup
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=14G
#SBATCH --time=02:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
mkdir -p "$LRAT_EVAL_ROOT" "$LRAT_DATA_ROOT" "$LRAT_SCRATCH_ROOT/manifests"
export UV_CONCURRENT_DOWNLOADS=3 UV_CONCURRENT_BUILDS=1 UV_CONCURRENT_INSTALLS=2
uv sync --project "$LRAT_REPO_ROOT/environments/snellius-eval" --locked --python 3.11.13
source "$LRAT_REPO_ROOT/scripts/snellius/eval_env.sh"
uv pip check --python "$VIRTUAL_ENV/bin/python"
srun python "$LRAT_REPO_ROOT/scripts/snellius/eval_prepare.py"
uv pip freeze --python "$VIRTUAL_ENV/bin/python" > "$LRAT_EVAL_ROOT/packages.txt"
printf 'Evaluation assets ready: %s\n' "$LRAT_EVAL_ASSETS"
