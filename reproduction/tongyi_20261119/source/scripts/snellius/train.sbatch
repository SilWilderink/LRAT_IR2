#!/usr/bin/env bash
#SBATCH --job-name=lrat-train
#SBATCH --partition=gpu_a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=18
#SBATCH --mem=100G
#SBATCH --time=00:20:00

set -euo pipefail
: "${SLURM_JOB_ID:?Submit this script with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/env.sh"
mode="${1:-smoke}"
case "$mode" in
    smoke) data="$LRAT_SCRATCH_ROOT/data/smoke.jsonl"; max_steps=2 ;;
    full) data="$LRAT_SCRATCH_ROOT/data/train.jsonl"; max_steps=-1 ;;
    *) printf 'Usage: sbatch train.sbatch [smoke|full] [checkpoint-directory]\n' >&2; exit 2 ;;
esac
[[ -x "$UV_PROJECT_ENVIRONMENT/bin/python" && -s "$data" ]] || {
    printf 'Run setup.sbatch first (LRAT_PREPARE_MODE=full for full training).\n' >&2; exit 1;
}
resume_from="${2:-${LRAT_RESUME_FROM:-}}"
resume_args=()
if [[ -n "$resume_from" ]]; then
    if [[ "$mode" != full ]]; then
        printf 'Checkpoint resumption is supported in full mode.\n' >&2; exit 2
    fi
    for required in trainer_state.json config.json optimizer.pt scheduler.pt rng_state.pth; do
        [[ -s "$resume_from/$required" ]] || {
            printf 'Missing resume state: %s/%s\n' "$resume_from" "$required" >&2; exit 1;
        }
    done
    [[ -s "$resume_from/model.safetensors" || -s "$resume_from/model.safetensors.index.json" ]] || {
        printf 'Missing model weights in %s\n' "$resume_from" >&2; exit 1;
    }
    resume_from="$(cd -- "$resume_from" && pwd -P)"
    resume_args=(--resume_from_checkpoint "$resume_from")
fi
: "${TMPDIR:?Snellius must provide job scratch via TMPDIR}"
work_dir="$(mktemp -d "$TMPDIR/lrat.XXXXXX")"
run_dir="$LRAT_RUN_ROOT/$mode-$SLURM_JOB_ID"
mkdir -p "$run_dir" "$work_dir/dataset-cache"
cp "$data" "$work_dir/train.jsonl"
cp "$LRAT_SCRATCH_ROOT/manifests/$mode-assets.json" "$run_dir/"
cp "$LRAT_REPO_ROOT/environments/snellius/uv.lock" "$run_dir/environment.lock"
git -C "$LRAT_REPO_ROOT" rev-parse HEAD > "$run_dir/git-commit.txt"
git -C "$LRAT_REPO_ROOT" diff > "$run_dir/code.diff"
if [[ -n "$resume_from" ]]; then
    printf '%s\n' "$resume_from" > "$run_dir/resumed-from.txt"
    printf 'Resuming from %s; writing new outputs to %s\n' "$resume_from" "$run_dir"
fi
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export TORCH_EXTENSIONS_DIR="$work_dir/torch-extensions"
export TRITON_CACHE_DIR="$work_dir/triton"
srun python "$LRAT_REPO_ROOT/scripts/snellius/check_gpu.py" | tee "$run_dir/gpu-check.txt"
model_path="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["model_path"])' "$LRAT_SCRATCH_ROOT/manifests/$mode-assets.json")"
gpu_count="${SLURM_GPUS_ON_NODE:-1}"
srun python -m torch.distributed.run --standalone --nnodes=1 --nproc_per_node="$gpu_count" \
    -m FlagEmbedding.finetune.embedder.decoder_only.base \
    --model_name_or_path "$model_path" \
    --cache_dir "$HF_HUB_CACHE" \
    --train_data "$work_dir/train.jsonl" \
    --cache_path "$work_dir/dataset-cache" \
    --output_dir "$run_dir/model" \
    --do_train True \
    --train_group_size "${LRAT_GROUP_SIZE:-2}" \
    --per_device_train_batch_size "${LRAT_BATCH_SIZE:-2}" \
    --gradient_accumulation_steps "${LRAT_GRAD_ACCUM:-1}" \
    --query_max_len 512 --passage_max_len 512 --pad_to_multiple_of 8 \
    --query_instruction_for_retrieval 'Given a web search query, retrieve relevant passages that answer the query' \
    --query_instruction_format 'Instruct: {}\nQuery:{}' \
    --knowledge_distillation False --same_dataset_within_batch False \
    --learning_rate 1e-6 --bf16 True --num_train_epochs 2 \
    --max_steps "$max_steps" --warmup_ratio 0.1 \
    --gradient_checkpointing True \
    --gradient_checkpointing_kwargs '{"use_reentrant": false}' \
    --ddp_find_unused_parameters False --dataloader_num_workers 0 \
    --dataloader_drop_last True --save_strategy steps \
    --save_steps 500 --save_total_limit 2 --logging_steps 1 \
    --sentence_pooling_method last_token --normalize_embeddings True \
    --temperature 0.02 --report_to none --seed 42 \
    "${resume_args[@]}" \
    2>&1 | tee "$run_dir/training.log"
python - "$run_dir/model" "$mode" <<'CHECK'
import json, math, sys
from pathlib import Path
output = Path(sys.argv[1])
states = sorted(output.glob("checkpoint-*/trainer_state.json"), key=lambda p: int(p.parent.name.split("-")[-1]))
if not states:
    raise SystemExit("Training produced no checkpoint state.")
state = json.loads(states[-1].read_text())
losses = [x["loss"] for x in state["log_history"] if "loss" in x]
if not losses or not all(math.isfinite(x) for x in losses):
    raise SystemExit("Missing or non-finite training losses.")
if sys.argv[2] == "smoke" and state["global_step"] != 2:
    raise SystemExit("Smoke training did not complete two steps.")
if not (output / "config.json").is_file() or not list(output.glob("*.safetensors")):
    raise SystemExit("Final model weights/config are missing.")
print("Validated checkpoint; losses:", losses)
CHECK
printf 'Completed %s run: %s\n' "$mode" "$run_dir"
