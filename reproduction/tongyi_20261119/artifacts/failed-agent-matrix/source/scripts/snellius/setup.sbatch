#!/usr/bin/env bash
#SBATCH --job-name=lrat-setup
#SBATCH --partition=staging
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=14G
#SBATCH --time=01:00:00

set -euo pipefail
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/env.sh"
mkdir -p "$LRAT_SCRATCH_ROOT"/{envs,cache,data,manifests} "$LRAT_RUN_ROOT" "$LRAT_DATA_ROOT"
: "${TMPDIR:?Snellius must provide job scratch via TMPDIR}"
export UV_CONCURRENT_DOWNLOADS=4
export UV_CONCURRENT_BUILDS=2
export UV_CONCURRENT_INSTALLS=2
uv sync --project "$LRAT_REPO_ROOT/environments/snellius" --locked --python 3.11.13
source "$LRAT_REPO_ROOT/scripts/snellius/env.sh"
uv pip check --python "$VIRTUAL_ENV/bin/python"
python "$LRAT_REPO_ROOT/scripts/snellius/prepare.py" "${LRAT_PREPARE_MODE:-smoke}"
python -m FlagEmbedding.finetune.embedder.decoder_only.base --help > "$LRAT_SCRATCH_ROOT/manifests/trainer-help.txt"
uv pip freeze --python "$VIRTUAL_ENV/bin/python" > "$LRAT_SCRATCH_ROOT/manifests/packages.txt"
printf 'Environment ready: %s\n' "$VIRTUAL_ENV/bin/python"
