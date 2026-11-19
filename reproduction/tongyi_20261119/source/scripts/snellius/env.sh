#!/usr/bin/env bash
# Source from the checkout; paths can be overridden before sourcing.
export LRAT_REPO_ROOT="${LRAT_REPO_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}"
if [[ -f "$LRAT_REPO_ROOT/scripts/snellius/local.sh" ]]; then
    source "$LRAT_REPO_ROOT/scripts/snellius/local.sh"
fi
export LRAT_SCRATCH_ROOT="${LRAT_SCRATCH_ROOT:-/scratch-shared/$USER/lrat}"
# Canonical datasets persist in home; prepared derivatives stay on scratch.
export LRAT_DATA_ROOT="${LRAT_DATA_ROOT:-/home/$USER/datasets/lrat}"
export LRAT_RUN_ROOT="${LRAT_RUN_ROOT:-$LRAT_SCRATCH_ROOT/runs}"
export UV_PROJECT_ENVIRONMENT="$LRAT_SCRATCH_ROOT/envs/train-py311"
export UV_CACHE_DIR="$LRAT_SCRATCH_ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$LRAT_SCRATCH_ROOT/python"
export HF_HOME="$LRAT_SCRATCH_ROOT/cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_DATASETS_CACHE="$LRAT_SCRATCH_ROOT/cache/datasets"
export XDG_CACHE_HOME="$LRAT_SCRATCH_ROOT/cache"
export PYTHONPATH="$LRAT_REPO_ROOT/FlagEmbedding${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export LRAT_MODEL_ID="${LRAT_MODEL_ID:-Qwen/Qwen3-Embedding-0.6B}"
export LRAT_MODEL_REVISION="${LRAT_MODEL_REVISION:-97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3}"
export LRAT_DATASET_ID="${LRAT_DATASET_ID:-Yuqi-Zhou/LRAT-Train}"
export LRAT_DATASET_REVISION="${LRAT_DATASET_REVISION:-26df12d39ec3eb65a30a61d86664931bb0fa4359}"
if [[ -x "$UV_PROJECT_ENVIRONMENT/bin/python" ]]; then
    export VIRTUAL_ENV="$UV_PROJECT_ENVIRONMENT"
    export PATH="$VIRTUAL_ENV/bin:$PATH"
fi
