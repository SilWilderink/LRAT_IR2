"""Download only the E5 backbone and reuse validated LRAT/benchmark data."""
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download
from eval_embedding import E5_RETRIEVAL

if not os.environ.get("SLURM_JOB_ID"):
    raise SystemExit("Submit e5_setup.sbatch through Slurm")
root = Path(os.environ["LRAT_SCRATCH_ROOT"])
training = json.loads((root / "manifests/full-assets.json").read_text())
if not Path(training["source_file"]).is_file() or not Path(training["prepared_file"]).is_file():
    raise RuntimeError("Canonical and prepared LRAT training data must already exist")
model_id = "intfloat/multilingual-e5-large-instruct"
revision = "274baa43b0e13e37fafa6428dbc7938e62e5c439"
model = snapshot_download(model_id, revision=revision, max_workers=2,
    allow_patterns=["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
                    "special_tokens_map.json", "sentencepiece.bpe.model"])
training.update(model_id=model_id, model_revision=revision, model_path=model,
                retrieval=E5_RETRIEVAL)
manifest = Path(os.environ["LRAT_E5_ASSETS"])
manifest.parent.mkdir(parents=True, exist_ok=True)
manifest.write_text(json.dumps(training, indent=2) + "\n")
benchmark = json.loads((root / "manifests/browsecomp-assets.json").read_text())
for key in ("corpus_database", "protocol_path", "agent_path", "judge_path"):
    if not Path(benchmark[key]).exists():
        raise RuntimeError("Missing shared benchmark asset: " + key)
benchmark.update(trained_model=os.environ["LRAT_EVAL_MODEL"], retrieval=E5_RETRIEVAL,
                 training_assets=str(manifest))
output = Path(os.environ["LRAT_EVAL_ASSETS"])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(benchmark, indent=2) + "\n")
print("E5 assets ready:", manifest, "Evaluation assets:", output, flush=True)
