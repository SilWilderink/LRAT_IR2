#!/usr/bin/env bash
#SBATCH --job-name=lrat-e5-train
#SBATCH --partition=gpu_a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gpus=1
#SBATCH --cpus-per-task=18
#SBATCH --mem=100G
#SBATCH --time=48:00:00
set -euo pipefail
: "${SLURM_JOB_ID:?Submit with sbatch}"
: "${LRAT_REPO_ROOT:=${SLURM_SUBMIT_DIR:?}}"
source "$LRAT_REPO_ROOT/scripts/snellius/env.sh"
: "${TMPDIR:?Snellius job scratch is required}"
: "${LRAT_E5_RUN_DIR:?Submit with submit_e5.py}"
work_dir="$(mktemp -d "$TMPDIR/lrat-e5.XXXXXX")"
mkdir -p "$LRAT_E5_RUN_DIR" "$work_dir/dataset-cache"
cp "$LRAT_SCRATCH_ROOT/data/train.jsonl" "$work_dir/train.jsonl"
cp "$LRAT_E5_ASSETS" "$LRAT_E5_RUN_DIR/assets-used.json"
cp "$LRAT_REPO_ROOT/environments/snellius/uv.lock" "$LRAT_E5_RUN_DIR/environment.lock"
cp "$LRAT_REPO_ROOT/scripts/snellius/e5_train.sbatch" "$LRAT_E5_RUN_DIR/train.sbatch"
cp "$LRAT_REPO_ROOT/FlagEmbedding/FlagEmbedding/finetune/embedder/encoder_only/base/modeling.py" "$LRAT_E5_RUN_DIR/encoder-modeling.py"
cp "$LRAT_REPO_ROOT/FlagEmbedding/FlagEmbedding/finetune/embedder/encoder_only/base/trainer.py" "$LRAT_E5_RUN_DIR/encoder-trainer.py"
git -C "$LRAT_REPO_ROOT" rev-parse HEAD > "$LRAT_E5_RUN_DIR/git-commit.txt"
git -C "$LRAT_REPO_ROOT" diff > "$LRAT_E5_RUN_DIR/code.diff"
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export TORCH_EXTENSIONS_DIR="$work_dir/torch-extensions"
export TRITON_CACHE_DIR="$work_dir/triton"
export TORCHINDUCTOR_CACHE_DIR="$work_dir/torchinductor"
model_path="$(python -c 'import json,os; print(json.load(open(os.environ["LRAT_E5_ASSETS"]))["model_path"])')"
resume_args=()
if [[ -n "${LRAT_E5_RESUME_FROM:-}" ]]; then
    resume_args=(--resume_from_checkpoint "$LRAT_E5_RESUME_FROM")
fi
srun python "$LRAT_REPO_ROOT/scripts/snellius/check_gpu.py" | tee "$LRAT_E5_RUN_DIR/gpu-check.txt"
srun python -m torch.distributed.run --standalone --nnodes=1 --nproc_per_node=1 \
    -m FlagEmbedding.finetune.embedder.encoder_only.base \
    --model_name_or_path "$model_path" --cache_dir "$HF_HUB_CACHE" \
    --train_data "$work_dir/train.jsonl" --cache_path "$work_dir/dataset-cache" \
    --output_dir "$LRAT_E5_RUN_DIR/model" --do_train True \
    --train_group_size 10 --per_device_train_batch_size 32 \
    --gradient_accumulation_steps 1 --sub_batch_size 8 \
    --query_max_len 512 --passage_max_len 512 --pad_to_multiple_of 8 \
    --query_instruction_for_retrieval 'Given a web search query, retrieve relevant passages that answer the query' \
    --query_instruction_format 'Instruct: {}\nQuery: {}' \
    --knowledge_distillation False --same_dataset_within_batch False \
    --negatives_cross_device False --learning_rate 1e-6 --bf16 True \
    --num_train_epochs 2 --warmup_ratio 0.1 --gradient_checkpointing True \
    --gradient_checkpointing_kwargs '{"use_reentrant": false}' \
    --ddp_find_unused_parameters True --dataloader_num_workers 0 \
    --dataloader_drop_last True --save_strategy steps --save_steps 100 \
    --save_total_limit 2 --logging_steps 1 --sentence_pooling_method mean \
    --normalize_embeddings True --temperature 0.02 --report_to none --seed 42 \
    "${resume_args[@]}" 2>&1 | tee "$LRAT_E5_RUN_DIR/training.log"
python - "$LRAT_E5_RUN_DIR" <<'CHECK'
import json, math, sys
from pathlib import Path
root = Path(sys.argv[1])
model = root / "model"
states = sorted(model.glob("checkpoint-*/trainer_state.json"), key=lambda p: int(p.parent.name.split("-")[-1]))
if not states:
    raise SystemExit("No training checkpoint")
state = json.loads(states[-1].read_text())
losses = [x["loss"] for x in state["log_history"] if "loss" in x]
if not losses or not all(math.isfinite(x) for x in losses):
    raise SystemExit("Training losses missing/non-finite")
if state["global_step"] != state["max_steps"] or state["epoch"] < 1.99:
    raise SystemExit("Training did not finish both epochs")
if not (model / "model.safetensors").is_file():
    raise SystemExit("Final model weights missing")
summary = {"global_step":state["global_step"], "epoch":state["epoch"], "batch_size":32,
           "group_size":10,"gpus":1,"cross_device_negatives":False,"pooling":"mean",
           "first_100_loss":sum(losses[:100])/len(losses[:100]),
           "last_100_loss":sum(losses[-100:])/len(losses[-100:])}
(root / "training-complete.json").write_text(json.dumps(summary,indent=2)+"\n")
print(json.dumps(summary,indent=2))
CHECK
