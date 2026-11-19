# LRAT reproduction experiment report on Snellius

Consolidated experiment record, updated 18 November 2026 (CET). Live job states are snapshots; use the monitoring commands below for subsequent changes.
**Current queue:** no running or pending jobs as of this update.

The agent in all completed evaluations is the fixed
`Alibaba-NLP/Tongyi-DeepResearch-30B-A3B` backbone. The retrievers below were
fine-tuned on the released LRAT-Train pairs; the agent was not fine-tuned.

| Retriever | Benchmark | Status | Correct | Success rate | Evidence recall | Avg. tool steps | Job |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Qwen3-Embedding-0.6B + LRAT | BrowseComp-Plus (830) | Completed, archived | 173/830 | 20.84% | 46.91% | 44.50 | 28913295 |
| Multilingual-E5-Large-Instruct + LRAT | BrowseComp-Plus (830) | Completed, archived | 218/830 | 26.27% | 56.89% | 43.19 | 28929763 |
| Qwen3-Embedding-0.6B + LRAT | InfoSeek-Eval (300) | Completed, archived | 200/300 | 66.67% | Not defined | 25.30 | 29004458 |
| Multilingual-E5-Large-Instruct + LRAT | InfoSeek-Eval (300) | Completed; outputs on scratch | 216/300 | 72.00% | Not defined | 24.43 | 29004459 |

The Qwen InfoSeek job completed on 10 November with Slurm state `COMPLETED`,
exit code `0:0`, and elapsed time `14:24:11`. Its report contains all 300
unique questions, 300 trajectories, and 300 judgments, with no reported
judging errors. Average model calls were 31.12. E5 job `29004459` completed on
11 November at 14:31:15 CET with Slurm state `COMPLETED`, exit code `0:0`,
and elapsed time `10:07:54`. Its final report contains 216 correct answers
out of 300 questions (72.00%), with all 300 trajectories and 300 judgments
present. Average model calls were 30.22.
The shared InfoSeek corpus preparation job `29004457` completed successfully.

Both retrievers completed two training epochs on 96,503 valid released
LRAT-Train examples. Qwen used batch/group size 2/2 on one A100; E5 used
32/10 on one A100 with sub-batches of eight. Both used learning rate `1e-6`,
temperature `0.02`, and maximum query/passage length 512. The
[training operations section](#training-operations) records the rest of the setup. Qwen's smaller
contrastive batch and group size differ from the paper's stated 32/10, while
E5's single-GPU negative pool differs from the released eight-GPU launcher.
The two backbone scores should therefore not be read as a controlled
comparison or as gains over base retrievers.

The [BrowseComp-Plus operations section](#browsecomp-plus-operations) documents its evaluation
protocol and the durable model/result archive at
`/gpfs/home6/scur0901/lrat-results/tongyi-browsecomp-plus-20261108/`.
The completed Qwen InfoSeek report, 300 trajectories and 300 judgments, and
run metadata are preserved at
`/gpfs/home6/scur0901/lrat-results/tongyi-infoseek-20261111/qwen3-embedding-0.6b-lrat/`.
Its `SHA256SUMS` and `archive-manifest.json` verify the copied files. The
11,215,099-document FAISS index and E5's completed outputs remain under
`/scratch-shared/scur0901/lrat/evaluation/infoseek-tongyi-20261108T205501Z/`.
Canonical Wiki and benchmark inputs are in permanent dataset storage, as
described in the [InfoSeek operations](#infoseek-operations).

## Eight additional agent/retriever/benchmark trials

The new matrix reuses the existing Qwen3-Embedding-0.6B and
Multilingual-E5-Large-Instruct LRAT checkpoints. Their supervision is the
released LRAT-Train data derived by the authors from Tongyi DeepResearch
trajectories on InfoSeekQA seed questions. We trained these retrievers from
those released pairs; we did not regenerate the seed trajectories.

Each retriever is evaluated with both `hkust-nlp/WebExplorer-8B` and
`openbmb/AgentCPM-Explore` on both InfoSeek-Eval (300 questions) and
BrowseComp-Plus (830 questions): eight full benchmark trials. Agent weights
remain fixed. All four previously built corpus/retriever indexes are reused.

Each trial has an agent job requesting **2 A100s, 36 CPUs, 220 GiB** and a
separate dependent judge job requesting **4 A100s, 72 CPUs, 440 GiB**. Agent
wall-time limits are 24 hours for InfoSeek and 48 hours for BrowseComp; judge
limits are three and six hours respectively. These are conservative limits,
not measured runtimes for the new agent backbones. A shared CPU staging job
first downloads the pinned agents, verifies model/index compatibility, and
checks the agent protocol. `afterok` dependencies prevent inference before
setup succeeds and judging before all agent trajectories finish.

Both new agents use the repository's WebExplorer ReAct prompt, as do the
upstream `webexplorer_client.py` and `agentcmp_client.py`. A completed plain
response is accepted as a final answer, matching those clients. Settings are
seed 2025, temperature 0.85, top-p 0.95, presence penalty 1.1, and at most 50
model calls, following the [paper's implementation details](https://arxiv.org/html/2604.04949v1#S6.SS1).
Retrieval returns ten documents with 64-token snippets and 512-token document
views. The bounded loop and generation caps retain the documented differences
from the unchanged upstream clients. The judge remains
Qwen3-30B-A3B-Thinking-2507. New trajectories additionally record explicit
successful search/browse document IDs for audit.

Code is snapshotted at submission; canonical datasets stay in permanent
storage, indexes and running outputs stay on scratch, and each successful
judging job archives its score report and per-question audit in home storage.

Shared preparation job **29122551** completed successfully in 00:06:47 (exit 0:0). All three protocol checks and all eight input validations passed.

Status checked on **18 November 2026**: no running or pending jobs, and no
replacement submissions found. All eight agent jobs failed on 12–13 November
with exit code `1:0`; all eight dependent judge jobs were cancelled before
starting. Each trial has zero trajectories and zero judgments, so no scores
are available. All agent server logs report that required GPUs exceed the
available GPUs in the Ray placement group; the launcher then fails its
30-minute server-readiness timeout. GPU allocation/visibility needs
investigation before rerunning these trials.

| Agent | Retriever | Benchmark | Agent job | Agent status | Elapsed | Judge job | Judge status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WebExplorer-8B | Qwen3-Emb + LRAT | InfoSeek-Eval | 29122552 | FAILED | 00:41:46 | 29122553 | CANCELLED |
| WebExplorer-8B | Qwen3-Emb + LRAT | BrowseComp-Plus | 29122554 | FAILED | 00:31:17 | 29122555 | CANCELLED |
| WebExplorer-8B | E5-Large + LRAT | InfoSeek-Eval | 29122556 | FAILED | 00:36:24 | 29122557 | CANCELLED |
| WebExplorer-8B | E5-Large + LRAT | BrowseComp-Plus | 29122558 | FAILED | 00:31:22 | 29122559 | CANCELLED |
| AgentCPM-Explore-4B | Qwen3-Emb + LRAT | InfoSeek-Eval | 29122560 | FAILED | 00:31:28 | 29122561 | CANCELLED |
| AgentCPM-Explore-4B | Qwen3-Emb + LRAT | BrowseComp-Plus | 29122562 | FAILED | 00:31:14 | 29122563 | CANCELLED |
| AgentCPM-Explore-4B | E5-Large + LRAT | InfoSeek-Eval | 29122564 | FAILED | 00:34:48 | 29122565 | CANCELLED |
| AgentCPM-Explore-4B | E5-Large + LRAT | BrowseComp-Plus | 29122567 | FAILED | 00:31:14 | 29122570 | CANCELLED |

Run configuration, frozen source and submission record:

```text
/scratch-shared/scur0901/lrat/evaluation/agent-matrix-20261111T122431Z
```

Each successful judge archives its report, trajectories and judgments under `/home/scur0901/lrat-results/agent-matrix-20261111T122431Z/<trial>/`.

No retraining or index rebuild is included. The existing retrievers retain their recorded training differences.

## BrowseComp-Plus browsed-document label audit

CPU staging job **29122640** completed successfully in 00:03:17. It analyzed
all 830 saved Tongyi trajectories for each trained retriever. Every parsed
successful document open was reconciled against the trajectory's saved tool
counters. Search-result snippets, failed opens, and invalid calls are excluded.

The primary unit is a unique **(question, document)** pair within each retriever
run; repeated opens of the same document for the same question count once.
Labels are positive entries in `qrel_evidence.txt` for the original benchmark
question, rather than for the agent's intermediate search query.

| Retriever | Browsed pairs absent from evidence labels | Percentage | Unlabeled browse events, including repeats | Event percentage |
| --- | ---: | ---: | ---: | ---: |
| Qwen3-Embedding-0.6B + LRAT | 852 / 1,946 | **43.78%** | 8,172 / 17,711 | 46.14% |
| Multilingual-E5-Large-Instruct + LRAT | 991 / 2,373 | **41.76%** | 7,027 / 17,656 | 39.80% |

Pooling pairs across the two runs gives **1,843 / 4,319 = 42.67%**. This
pooling retains retriever-run identity. Qwen had 110 questions with no
successful browse and E5 had 71; those questions contribute no document pairs.
Using the narrower `qrel_golds.txt` labels instead gives 69.32% for Qwen and
68.39% for E5. The evidence-label percentages above are the primary result.

Among pairs from correctly answered tasks, 112/578 (19.38%) for Qwen and
180/853 (21.10%) for E5 were absent from evidence labels. Absence from a label
set does **not** establish irrelevance to reasoning. For example, in
`qwen:1144:32` (document 11403), the agent used an unlabeled article to reject
a candidate because the incident date did not fit the question; the final
answer for that task was correct. This illustrates candidate elimination,
not proof that every unlabeled document was useful.

The permanent review archive is
`/gpfs/home6/scur0901/lrat-results/browse-audit-20261111/`:

- [review_pairs.csv](/gpfs/home6/scur0901/lrat-results/browse-audit-20261111/review_pairs.csv): all **1,843** unlabeled pairs, visit counts, task correctness, question text, and blank usefulness/notes columns for manual annotation.
- [review_sample.md](/gpfs/home6/scur0901/lrat-results/browse-audit-20261111/review_sample.md): 20 deterministic examples spanning both retrievers and correct/incorrect tasks.
- `browse_events.jsonl.gz`: all successful browse events, including the exact document view, preceding search query, and assistant messages immediately before and after browsing. Join CSV rows using `first_event_id`.
- `summary.json`, `audit_browsed.py`, and `SHA256SUMS`: aggregate counts, reproducible parser, and verified archive checksums.

The detailed event archive contains 35,367 successful browse events. Document views are the original 512-token tool outputs. The CSV contains 292 unlabelled pairs from correctly answered tasks; filter `task_correct` to begin with those cases. For incorrectly answered tasks, the unlabelled-pair shares are 54.09% (Qwen) and 53.36% (E5).

## Remaining reproduction work

Diagnose and fix the GPU startup failure, then rerun the eight new trials
and their dependent judging jobs. Preserve the completed E5 InfoSeek outputs
in durable storage; its report and per-question outputs currently remain on
scratch. Base-retriever
comparisons remain deferred, so improvements over base models cannot yet be
claimed. Other paper agents, ablations, retraining with the paper's full
configuration, and regeneration of training trajectories/supervision also
remain outstanding. These results are a partial reproduction with the
training and evaluation differences recorded here.

To refresh the live status:

```bash
sacct -X -j 29122551,29122552,29122553,29122554,29122555,29122556,29122557,29122558,29122559,29122560,29122561,29122562,29122563,29122564,29122565,29122567,29122570 \
  --format=JobID,State,ExitCode,Elapsed,End
sacct -X -j 29004457,29004458,29004459 \
  --format=JobID,JobName,State,ExitCode,Elapsed,Start,End
squeue -u "$USER"
```

## Training operations

The following commands document setup, retriever training, and historical resume procedures. The completed-run status is recorded at the top of this report.

This workflow starts from the released LRAT-Train training pairs and
Qwen/Qwen3-Embedding-0.6B. It prepares a small training validation before a
larger reproduction run. Code stays in the home checkout. Canonical datasets
are stored permanently under `LRAT_DATA_ROOT` (default: `/home/$USER/datasets/lrat`).
Models, Python environment, caches, prepared training files, intermediate
checkpoints, and logs go to scratch.

### Environment

The upstream checkout contains a root `uv.lock` but no `pyproject.toml`.
Consequently the README's root-level `uv sync` is not usable in this checkout.
The separate project in `environments/snellius/` has its own manifest and
lock, leaving the upstream lock intact.

Core versions match the upstream lock: Python 3.11.13, PyTorch 2.7.0
(CUDA 12.6 runtime on Linux), Transformers 4.53.2, Datasets 4.0.0,
Accelerate 1.9.0, PEFT 0.16.0, and NumPy 1.26.4.
The local modified FlagEmbedding is installed editable.
Additional dependencies are locked to releases available by July 17, 2025.

The environment targets Linux x86_64. This fine-tuning setup uses PyTorch's
built-in attention support. External FlashAttention, DeepSpeed, Java, vLLM,
and retrieval indexes are unnecessary for this first single-GPU workflow.
Reproducing the original eight-GPU training recipe requires further
resource and hyperparameter choices.

### Storage

| Content | Default location |
| --- | --- |
| Source and small configuration files | This checkout in home |
| Environment | `/scratch-shared/$USER/lrat/envs/train-py311` |
| Managed Python interpreter | `/scratch-shared/$USER/lrat/python` |
| uv and Hugging Face caches | `/scratch-shared/$USER/lrat/cache/` |
| Canonical source dataset and checksum | `/home/$USER/datasets/lrat/Yuqi-Zhou--LRAT-Train/<revision>/` |
| Prepared training JSONL (derived working copy) | `/scratch-shared/$USER/lrat/data/` |
| Batch logs | `/scratch-shared/$USER/lrat/logs/` |
| Checkpoints and training logs | `/scratch-shared/$USER/lrat/runs/` |
| Per-job input copy and temporary Arrow/compiler caches | `$TMPDIR/lrat.*` |

Snellius scratch is temporary and has no backup. Unused scratch-shared files
are subject to automatic cleanup after 14 days. Copy valuable checkpoints,
metrics, and logs to your project's persistent storage or other durable
storage before they expire. Do not use system `/tmp` for experiment data.
Use the job's actual `$TMPDIR`, rather than constructing a node-specific path.

These choices follow SURF's
[file-system guidance](https://servicedesk.surf.nl/wiki/spaces/WIKI/pages/30661930/Snellius+hardware+and+file+systems).
Run training and GPU checks through Slurm; SURF's
[login-node policy](https://servicedesk.surf.nl/wiki/spaces/WIKI/pages/30660216/Connecting+to+the+system)
reserves login nodes for job preparation, submission, and data management.

### First setup and smoke run

Run from the checkout:

```bash
source scripts/snellius/env.sh
# If Slurm needs an explicit account:
# export LRAT_ACCOUNT=your-account
bash scripts/snellius/submit.sh
```

The wrapper submits two jobs:

1. `setup.sbatch` on `staging`: install the locked environment, prepare
   64 valid examples streamed from the released data, download the pinned
   0.6B model, and check the training CLI. The full 3.88 GB training JSONL
   is not downloaded for this smoke run.
2. `train.sbatch smoke` on `gpu_a100`: after setup succeeds, request one
   A100 with 18 CPU cores, check CUDA, and perform two training steps.

Both model and data revisions are pinned in `env.sh`. The preparation
manifest records revisions, row counts, skipped invalid rows, and a SHA256
of the prepared data. Model weights are downloaded during preparation;
the GPU job uses offline mode. Run outputs go directly to shared scratch,
so they do not depend on recovering files from job temporary storage.

Check status and logs:

```bash
squeue -u "$USER"
source scripts/snellius/env.sh
ls "$LRAT_SCRATCH_ROOT/logs"
# Replace JOB_ID with the printed ID:
sacct -j JOB_ID --format=JobID,JobName,State,ExitCode,Elapsed
tail -n 40 "$LRAT_SCRATCH_ROOT/logs/smoke-JOB_ID.out"
```

A successful smoke run prints two finite losses, saves a model/checkpoint,
and ends with `Completed smoke run:`. This validates wiring and GPU
execution; it does not reproduce paper accuracy.

To activate the environment in a new terminal after setup:

```bash
source scripts/snellius/env.sh
python --version
```

In VS Code, choose **Python: Select Interpreter → Enter interpreter path**:

```text
/scratch-shared/scur0901/lrat/envs/train-py311/bin/python
```

Replace the username for another account. Do not launch training using
VS Code's Run button on the login node.

For a manual software-only reinstall, with no experiment execution:

```bash
source scripts/snellius/env.sh
UV_CONCURRENT_DOWNLOADS=2 UV_CONCURRENT_INSTALLS=2 UV_CONCURRENT_BUILDS=1 \
  uv sync --project environments/snellius --locked --python 3.11.13
```

### Prepare all training pairs

After the smoke run succeeds:

```bash
source scripts/snellius/env.sh
sbatch --account="$LRAT_ACCOUNT" --export=ALL,LRAT_PREPARE_MODE=full \
  --output="$LRAT_SCRATCH_ROOT/logs/setup-full-%j.out" \
  scripts/snellius/setup.sbatch
```

This stages the pinned download through a scratch cache, then stores the
completed source JSONL and checksum in permanent storage under
`$LRAT_DATA_ROOT/Yuqi-Zhou--LRAT-Train/$LRAT_DATASET_REVISION/`. Future
preparation reuses this permanent source. It validates records and writes
`$LRAT_SCRATCH_ROOT/data/train.jsonl` as a derived working copy, preserving
the supplied weights. The GPU job copies that working file into `$TMPDIR`.
Expect about 3.9 GB for the permanent source, plus scratch space for the
download cache, prepared JSONL, Arrow caches, environment, and checkpoints. Invalid records are counted in the manifest.
The raw trajectories and corpus are unnecessary for training on these
released pairs. The source is the
[released LRAT-Train dataset](https://huggingface.co/datasets/Yuqi-Zhou/LRAT-Train).

### Resume an interrupted full-data run

Historical example: the original Qwen run was resumed from step 48,251 (one
complete epoch) and has since completed. The command used was:

```bash
source scripts/snellius/env.sh
checkpoint="$LRAT_SCRATCH_ROOT/runs/full-28800049/model/checkpoint-48251"
sbatch --account="$LRAT_ACCOUNT" --time=12:00:00 --export=ALL \
  --output="$LRAT_SCRATCH_ROOT/logs/train-resume-%j.out" \
  scripts/snellius/train.sbatch full "$checkpoint"
```

Run this from the repository root. Keep one GPU, batch size 2, group size 2,
and gradient accumulation 1 to continue the same run. The checkpoint restores
weights, optimizer, scheduler, RNG state, and step count; two epochs means
**two epochs in total**, leaving one epoch to train. The unsaved progress
between step 48,251 and the timeout at about step 76,329 must be repeated.
The new job writes to its own scratch run directory and leaves the old run
and checkpoint intact. Twelve hours is a wall-time request, not a guarantee
of the remaining runtime.

The launcher also accepts `LRAT_RESUME_FROM`, but the positional checkpoint
argument above avoids reliance on exported shell variables. Missing resume
files cause an early failure. The custom decoder trainer restores encoder
weights into its inner model, matching its checkpoint save format; the
standard Trainer handles the remaining training state.

Checkpoints now save every 500 optimizer steps and retain the latest two
in the new run directory. This interval matches the saved trainer state. The completed model is saved at `<new-run>/model/`. Check Slurm for
`COMPLETED` with exit code `0:0`; a `TIMEOUT` is incomplete even if the exit
code appears as `0:0`.

The tiny checkpoint restore regression check can be run without a GPU:

```bash
sbatch --account="$LRAT_ACCOUNT" --export=ALL \
  --output="$LRAT_SCRATCH_ROOT/logs/resume-check-%j.out" \
  scripts/snellius/check_resume.sbatch
```

### Run longer training

Wait for full data preparation to succeed, then:

```bash
source scripts/snellius/env.sh
sbatch --account="$LRAT_ACCOUNT" --time=12:00:00 \
  --output="$LRAT_SCRATCH_ROOT/logs/train-full-%j.out" \
  scripts/snellius/train.sbatch full
```

The default is a conservative single-GPU configuration: two epochs, batch
size 2, group size 2, maximum query/passage length 512, learning rate 1e-6,
BF16, non-reentrant gradient checkpointing, last-token pooling, and normalized embeddings.
Unused-parameter detection is disabled for the distributed wrapper; these
settings avoid duplicate-ready errors when the encoder processes both queries
and passages in one training step. See the
[PyTorch 2.7 DDP checkpointing notes](https://docs.pytorch.org/docs/2.7/generated/torch.nn.parallel.DistributedDataParallel.html).
It trains the full model and uses the local weighted contrastive loss.
The smoke run overrides training length to two steps.

These reduced batch/group sizes are for bringing up the environment;
they are not the repository's eight-GPU recipe (batch size 32, group size
10, cross-device negatives, and DeepSpeed). Treat this as a working
starting point, not an exact paper reproduction. Measure memory and
throughput before scheduling a full run; the 12-hour request above is a
wall-time allocation, not a runtime estimate.

Batch size, group size, and gradient accumulation can be set using
`LRAT_BATCH_SIZE`, `LRAT_GROUP_SIZE`, and `LRAT_GRAD_ACCUM`.
Keep batch size at least 2: this implementation normalizes example weights
within the loss, so a batch of one cancels the example's relative weight.
GPU count is read from the Slurm allocation; keep one node.
If moving to multiple GPUs, also match the intended negatives and
distributed-training settings before comparing results with the paper.

Optional overrides can be placed in the ignored
`scripts/snellius/local.sh`, for example:

```bash
export LRAT_ACCOUNT=your-account
export LRAT_SCRATCH_ROOT=/scratch-shared/$USER/lrat
export LRAT_DATA_ROOT=/home/$USER/datasets/lrat
# Alternatively, use an allocated permanent project directory for the dataset:
# export LRAT_DATA_ROOT=/projects/your-project/datasets/lrat
# Use a persistent project path you have access to for valuable run outputs:
# export LRAT_RUN_ROOT=/projects/your-project/lrat-runs
```

The run directory includes the asset manifest, environment lock, Git
commit, tracked diff, GPU check, and training log. Keep this source checkout
and its editable package available while queued jobs run. An idle scratch
environment may eventually be cleaned; rebuild it using the setup job.

## BrowseComp-Plus operations

This section preserves the original submission history and operational commands. Its initial jobs and timing estimates describe the completed Tongyi pipelines.

This workflow evaluates the completed pilot-trained Qwen3 retriever at
`$LRAT_RUN_ROOT/full-28880868/model` with Tongyi-DeepResearch-30B-A3B.
It does not run a base-retriever baseline. The retriever was trained with
reduced batch/group sizes, so results are a pilot reproduction rather than
an exact match of the paper's training recipe.

The evaluation targets all 830 BrowseComp-Plus questions. Corpus revision,
model revisions, protocol files/checksums, and generation settings are saved
in `$LRAT_EVAL_ROOT/assets.json` and each trajectory.

### Stages and submitted jobs

| Stage | Initial job | Resources | Wall-time allocation |
| --- | --- | --- | --- |
| Environment, corpus, model downloads | 28890789 | Staging, 2 CPUs | 2 hours |
| Encode corpus with trained retriever | 28890962 | 1 A100, 18 CPUs | 2 hours |
| Timing pilot: 16 fixed random questions plus judging | 28890963 | 4 A100s, 72 CPUs | 2 hours |
| Remaining questions plus judging | Automatically submitted after successful pilot | 4 A100s, 72 CPUs | Measured estimate plus margin |

Each stage depends on the preceding stage succeeding. Infrastructure errors
stop the pipeline rather than silently turning missing outputs into scores.
The full evaluation job ID will be written to `full-job.json`. Only this
pipeline's pilot subset is reused; no baseline run is involved.

The separate locked environment in `environments/snellius-eval/` uses
vLLM 0.10.2 and Transformers 4.55.2. The training environment is unchanged.

### Additional E5-Large + Tongyi experiment

A second independent pipeline was submitted on 4 November 2026. The paper's
E5-Large backbone is `intfloat/multilingual-e5-large-instruct`, pinned at
`274baa43b0e13e37fafa6428dbc7938e62e5c439`. Tongyi is the downstream agent;
the E5 retriever is fine-tuned on the shared released LRAT-Train dataset.

| Stage | Job | Dependency | Resources / time limit |
| --- | --- | --- | --- |
| E5 loss/pooling/resume regression checks and model download | 28906905 | None | Staging, 2 CPUs / 1 hour |
| Full-data E5 retriever training | 28906907 | Setup succeeds | 1 A100 / 48 hours |
| Encode corpus using the trained E5 model | 28906908 | Training succeeds | 1 A100 / 2 hours |
| Tongyi timing pilot and judging | 28906909 | E5 index succeeds | 4 A100s / 2 hours |
| Remaining BrowseComp-Plus questions and judging | Automatic after successful pilot | Pilot succeeds | 4 A100s / measured allocation |

The original E5 training job `28893826` failed on its second forward call
because DDP was configured with `find_unused_parameters=False`, while the
XLM-RoBERTa pooler is unused by mean-pooled embeddings. Its index/pilot jobs
`28893827` and `28893828` were automatically cancelled. The launcher now enables
unused-parameter detection and the replacement setup checks the exact two-step
failure path. No resumable checkpoint was saved, so the replacement training
starts from the same pinned base model in a new run directory. The original
run and logs are preserved under the `20261104T125425Z` tag.

This chain has no dependency on the existing Qwen evaluation, so Slurm can
schedule both pipelines concurrently. Failed prerequisites cancel dependent
jobs. Baseline evaluation remains deferred. Both evaluations cover the same
830 BrowseComp-Plus questions and use the same fixed 16-question timing subset.

E5 training uses two epochs, actual batch size 32, group size 10, learning
rate 1e-6, temperature 0.02, and maximum input length 512. Sub-batches of 8
reduce activation memory while retaining all 32 queries and 320 passages in
the contrastive batch. Example weights are applied to the in-batch loss.
The encoder trainer also restores raw encoder checkpoints into the inner
model on resume. The setup job runs regression checks for weighted loss/gradients, pooling,
checkpoint restoration, and two consecutive DDP steps with gradient
checkpointing and an unused encoder pooler. Training is gated on these checks.

Training and evaluation both use normalized, attention-mask-aware mean
pooling, right padding, and `Instruct: <instruction>\nQuery: <query>` for
queries; passages have no prefix, following the E5 model card. The E5
retrieval settings are recorded in its assets, corpus index, and trajectories.

The batch size matches the paper's stated value, interpreted as 32 total
queries per optimizer step on one GPU. The released example launcher instead
uses eight GPUs with batch 32 per device and cross-device negatives. This
single-GPU E5 run does not claim equivalence with that distributed launcher.
The 48-hour training allocation is a conservative limit, not measured runtime;
the first training steps will provide a throughput estimate. Agent evaluation
retains the provisional 8–24 hour range until its own timing pilot completes.

E5 outputs are separate from the Qwen experiment:

```text
/scratch-shared/scur0901/lrat/runs/e5-large-tongyi-20261104T204422Z/
/scratch-shared/scur0901/lrat/evaluation/e5-large-tongyi-20261104T204422Z/
```

The second directory contains `submitted-jobs.json`, `assets.json`, the E5
index, trajectories, judgments, runtime estimate, and final results as their
stages complete. Canonical training/benchmark data remain in permanent
storage; the shared corpus database and agent/judge model downloads are reused.
The original Qwen-specific `trained_model` entry in the shared manifest remains
unchanged: E5 jobs receive a separate `LRAT_EVAL_ASSETS` path.

Monitor the E5 chain with:

```bash
sacct -X -j 28906905,28906907,28906908,28906909 \
  --format=JobID,JobName,State,ExitCode,Elapsed
```

To submit another independent E5 run intentionally:

```bash
source scripts/snellius/env.sh
python scripts/snellius/submit_e5.py --submit
```

Omit `--submit` to inspect its configuration without creating jobs. Each
submission creates distinct scratch run/evaluation directories.

### Storage

Source corpus Parquet files and the exact query/qrel copies are stored under:

```text
$LRAT_DATA_ROOT/BrowseComp-Plus/b27b02bc3e45511b8b82a13e6f90ce761df726f6/
```

Model downloads, the SQLite document lookup, trained-retriever FAISS index,
trajectories, judgments, metrics, runtime measurements, and logs are on
scratch. Per-job kernel caches use `$TMPDIR`.

Default evaluation root:

```text
/scratch-shared/scur0901/lrat/evaluation/tongyi-trained-28880868/
```

The setup downloads about 1.76 GB of compressed corpus data and approximately
120 GB of agent/judge model weights. These downloads are separate from
evaluation compute time and may vary with network throughput.

### Runtime estimate

The preliminary planning range is **8–24 hours of agent/judge compute on
four A100s**, excluding software/data setup, index creation, and queue waits.
This is provisional, not a measurement.

The pilot selects 16 questions uniformly without replacement using seed
2025, with eight concurrent workers. It runs both agent inference and
judging. The controller records actual throughput and both server startup
times, then extrapolates the remaining 814 questions. It allocates the full
job with 60% headroom plus 30 minutes, rounding up to whole hours. The
reported range is a planning range, not a statistical confidence interval.
Heavy-tail query lengths make exact completion times uncertain.

Inspect the measured estimate and subsequently submitted full job:

```bash
source scripts/snellius/eval_env.sh
cat "$LRAT_EVAL_ROOT/runtime-estimate.json"
cat "$LRAT_EVAL_ROOT/full-job.json"
```

These files appear only after the pilot succeeds. If the pilot fails, inspect
its logs; the full job is not submitted. Do not infer successful full
evaluation from a successful setup/index/pilot job.

### Protocol and implementation

- Agent: Tongyi-DeepResearch-30B-A3B, pinned revision.
- Judge: Qwen3-30B-A3B-Thinking-2507, pinned revision.
- Agent generation: seed 2025, temperature 0.85, top-p 0.95, presence penalty 1.1.
- Retrieval: trained model only; last-token pooling, normalized vectors,
  query/passage encoding length 512, top 10 hits, 64-token snippets.
- Document viewing: 512 tokens, matching the repository tool implementation.
- At most 50 model calls; the last available call requests a final answer.
- Generation caps follow the local ReAct client: 4096, 2048, then 1024;
  a forced final answer allows 10000 tokens.
- The existing repository system and judge prompts are read verbatim.
- The local client hard-codes seed 2026 and temperature 0.6 despite its CLI
  options. This evaluation explicitly uses the paper's stated settings.
- A dedicated bounded loop avoids the local client's extra post-budget call
  and shared mutable state across concurrent questions.
- The judge receives only the question, final answer, and reference answer.
  Reference answers are never passed to the agent.
- API/model-server failures are recorded separately and cause a nonzero exit.
  Natural no-answer outcomes remain in the denominator.

These choices use the [paper's evaluation setup](https://arxiv.org/html/2604.04949v1#S6.SS1)
and the repository's ReAct prompts/tool formatting. They are documented
rather than claiming bit-for-bit equivalence with the original experiments.

### Outputs and monitoring

```bash
squeue -u "$USER"
sacct -X -j 28890789,28890962,28890963 \
  --format=JobID,JobName,State,ExitCode,Elapsed
ls "$LRAT_SCRATCH_ROOT/logs"/eval-*
```

Server startup logs are under the evaluation root. Per-question files are
written atomically in `trajectories/` and `judgments/`; completed questions
are reused on a subsequent full run with the same evaluation root.

The completed score report is `full-results.json`, containing 830 details
and the following metrics:

- `Success Rate`
- `Avg Steps`: successful tool calls, matching the repository evaluator
- `Evidence Recall`: macro-average evidence-document recall, matching that evaluator
- Additional audit metrics: average model calls and any-evidence hit rate

`pilot-results.json` contains only the 16 pilot questions and is not the full
benchmark score. Low-level retrieval scores alone do not establish end-to-end
agent success.

To rerun an interrupted full evaluation after inspecting the error:

```bash
source scripts/snellius/eval_env.sh
# Set the time using runtime-estimate.json and remaining work.
sbatch --account="$LRAT_ACCOUNT" --job-name=lrat-eval-full \
  --time=24:00:00 --export=ALL \
  --output="$LRAT_SCRATCH_ROOT/logs/eval-full-%j.out" \
  scripts/snellius/eval_run.sbatch full
```

Do not submit a duplicate while another full evaluation is active. Preserve
the completed model and final scores in durable storage before scratch
cleanup.


## InfoSeek operations

This section preserves the Tongyi InfoSeek submission, storage layout, and monitoring commands.

| Stage | Job | Resources / time limit |
| --- | --- | --- |
| Shared corpus preparation and CPU regression checks | 29004457 | Staging, 8 CPUs, 32 GiB / 12 hours |
| Qwen Wiki indexing, Tongyi inference and judging | 29004458 | 4 A100s, 72 CPUs, 440 GiB / 72 hours |
| E5 Wiki indexing, Tongyi inference and judging | 29004459 | 4 A100s, 72 CPUs, 440 GiB / 72 hours |

Both GPU jobs require successful shared preparation. Each first encodes four
non-overlapping corpus shards concurrently, assembles an exact normalized
FAISS inner-product index, then uses the same four GPUs for the Tongyi server
and subsequently the Qwen judge server. Independent GPU jobs can run concurrently.

The canonical corpus is the paper-linked `Lk123/wiki-25-512`, revision
`fc1e312568b14385c04f41bc09157d8fa4c20658`. Its JSONL file is 18,496,937,987 bytes,
with SHA-256 `4d795938bb89cbd7e7467a8da4e772f7ae95e6b533181aeace2a5e3fd3de6393`.
Preparation validates that hash, the `id`/`contents` schema, document IDs,
and all 300 question/answer triples. The exact document count is recorded
in `corpus/manifest.json` after reading the whole file.

Canonical data are kept under the permanent home dataset root:

```text
/home/scur0901/datasets/lrat/Wiki-25-512/fc1e312568b14385c04f41bc09157d8fa4c20658/
/home/scur0901/datasets/lrat/InfoSeek-Eval/6949cbe5e52088ba681ff5b2c236cb80785d1b769500655ffa21b7452ef62a02/
```

The trained model inputs are the SHA-256-verified archive copies:

```text
/home/scur0901/lrat-results/tongyi-browsecomp-plus-20261108/qwen3-embedding-0.6b-lrat/model/
/home/scur0901/lrat-results/tongyi-browsecomp-plus-20261108/multilingual-e5-large-instruct-lrat/model/
```

All prepared corpus databases, embedding shards, FAISS indexes, trajectories,
judgments, source snapshots, and run logs are on scratch:

```text
/scratch-shared/scur0901/lrat/evaluation/infoseek-tongyi-20261108T205501Z/
```

This root contains `configuration.json`, `submitted-jobs.json`, the shared
`corpus/`, and separate `qwen/` and `e5/` evaluation directories. Each model
subdirectory contains `assets.json`, `full-job.json`, `index/`, `trajectories/`,
`judgments/`, and `full-results.json` as those stages complete.

The Wiki corpus has roughly 11 million chunks, over 100 times the size of
BrowseComp-Plus. Index building is a substantial additional stage. The 72-hour
GPU allocation is a conservative limit; it is not a measured completion
estimate and excludes queue wait. Shard logs report document throughput.
Encoding progress is checkpointed every 4,096 documents per shard and can be
reused on a rerun with the same model, corpus, settings, and evaluation root.

The setup runs CPU checks for question integrity, absence of fabricated
InfoSeek evidence-recall metrics, unchanged BrowseComp scoring, and preservation
of vector order/nonsequential document IDs when uneven encoding shards merge.

Agent settings retain the previous trained-model evaluation protocol: seed
2025, temperature 0.85, top-p 0.95, presence penalty 1.1, at most 50 model calls,
top 10 retrieved documents, 64-token snippets, and 512-token document views.
The frozen agent/judge revisions and model-specific retrieval settings are
recorded in each assets file. Qwen uses last-token pooling; E5 uses masked mean
pooling. Both use normalized embeddings and 512-token encoding limits.

InfoSeek scores include Success Rate and Average Steps, with Average Model
Calls as an audit metric. It has no evidence-document qrels, so no Evidence
Recall is reported. The custom agent loop and judge settings retain the
previously documented differences from the unchanged upstream clients.

Monitor with:

```bash
sacct -X -j 29004457,29004458,29004459 \
  --format=JobID,JobName,State,ExitCode,Elapsed
squeue -u "$USER"
tail -n 30 /scratch-shared/scur0901/lrat/logs/infoseek-setup-29004457.out
tail -n 30 /scratch-shared/scur0901/lrat/logs/infoseek-qwen-29004458.out
tail -n 30 /scratch-shared/scur0901/lrat/logs/infoseek-e5-29004459.out
```

For an intentional separate submission, source `scripts/snellius/env.sh` and
run `python scripts/snellius/submit_infoseek.py --submit`. Omit `--submit` to
inspect configuration without creating jobs. Do not duplicate an active run.
