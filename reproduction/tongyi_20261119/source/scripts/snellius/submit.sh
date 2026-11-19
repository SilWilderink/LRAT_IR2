#!/usr/bin/env bash
# Queue asset preparation and, after success, one short GPU training validation.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
mkdir -p "$LRAT_SCRATCH_ROOT/logs"
account_args=()
if [[ -n "${LRAT_ACCOUNT:-}" ]]; then
    account_args=(--account="$LRAT_ACCOUNT")
fi
setup_id="$(sbatch --parsable "${account_args[@]}" \
    --chdir="$LRAT_REPO_ROOT" --export=ALL \
    --output="$LRAT_SCRATCH_ROOT/logs/setup-%j.out" \
    "$LRAT_REPO_ROOT/scripts/snellius/setup.sbatch")"
setup_id="${setup_id%%;*}"
train_id="$(sbatch --parsable "${account_args[@]}" \
    --chdir="$LRAT_REPO_ROOT" --export=ALL \
    --dependency="afterok:$setup_id" --kill-on-invalid-dep=yes \
    --output="$LRAT_SCRATCH_ROOT/logs/smoke-%j.out" \
    "$LRAT_REPO_ROOT/scripts/snellius/train.sbatch" smoke)"
printf 'Setup job: %s\nSmoke job: %s\nLogs: %s/logs\n' "$setup_id" "$train_id" "$LRAT_SCRATCH_ROOT"
