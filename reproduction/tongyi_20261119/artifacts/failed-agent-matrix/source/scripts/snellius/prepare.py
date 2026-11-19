"""Keep pinned source data in permanent storage and prepare scratch working files."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import requests
from huggingface_hub import hf_hub_download, hf_hub_url, snapshot_download

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mode", choices=["smoke", "full"])
args = parser.parse_args()
if not os.environ.get("SLURM_JOB_ID"):
    raise SystemExit("Submit setup.sbatch to prepare assets through Slurm.")
root = Path(os.environ["LRAT_SCRATCH_ROOT"])
data_dir = root / "data"
data_dir.mkdir(parents=True, exist_ok=True)
permanent_root = Path(os.environ["LRAT_DATA_ROOT"])
dataset_id = os.environ["LRAT_DATASET_ID"]
dataset_revision = os.environ["LRAT_DATASET_REVISION"]
filename = "LRAT-training-pairs.jsonl"
model_id = os.environ["LRAT_MODEL_ID"]
model_revision = os.environ["LRAT_MODEL_REVISION"]
source_dir = permanent_root / dataset_id.replace("/", "--") / dataset_revision
source_path = source_dir / filename
source_manifest_path = source_dir / "source.json"
source_metadata = None

def valid_record(record):
    if not isinstance(record.get("query"), str) or not record["query"].strip():
        return False
    for key in ("pos", "neg"):
        if not isinstance(record.get(key), list) or not record[key]:
            return False
        if any(not isinstance(x, str) or not x.strip() for x in record[key]):
            return False
    weight = record.get("reweight_rate", 1.0)
    return isinstance(weight, (int, float)) and math.isfinite(weight) and weight > 0

if args.mode == "full":
    if not source_path.is_file():
        cached = hf_hub_download(
            dataset_id, filename, repo_type="dataset", revision=dataset_revision,
            cache_dir=root / "cache" / "dataset-downloads",
        )
        source_dir.mkdir(parents=True, exist_ok=True)
        # Copy only a completed download into permanent storage. Rename within
        # that filesystem so an interrupted copy cannot become the source data.
        pending = source_path.with_name(filename + ".copy-" + os.environ["SLURM_JOB_ID"])
        raw_digest = hashlib.sha256()
        try:
            with open(cached, "rb") as src, pending.open("wb") as dst:
                while chunk := src.read(8 * 1024 * 1024):
                    dst.write(chunk)
                    raw_digest.update(chunk)
            source_metadata = {
                "dataset_id": dataset_id, "dataset_revision": dataset_revision,
                "filename": filename, "bytes": pending.stat().st_size,
                "sha256": raw_digest.hexdigest(),
            }
            pending.replace(source_path)
            source_manifest_path.write_text(json.dumps(source_metadata, indent=2) + "\n")
        except BaseException:
            pending.unlink(missing_ok=True)
            raise
        print("Permanent source dataset:", source_path, flush=True)
    source_context = source_path.open("rb")
    output = data_dir / "train.jsonl"
elif source_path.is_file():
    source_context = source_path.open("rb")
    output = data_dir / "smoke.jsonl"
else:
    # Stop after 64 usable rows; do not download the 3.88 GB file for a smoke run.
    url = hf_hub_url(dataset_id, filename, repo_type="dataset", revision=dataset_revision)
    headers = {}
    if os.environ.get("HF_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["HF_TOKEN"]
    source_context = requests.get(url, stream=True, timeout=(30, 120), headers=headers)
    source_context.raise_for_status()
    output = data_dir / "smoke.jsonl"

count = skipped = 0
digest = hashlib.sha256()
partial = output.with_suffix(".partial")
try:
    with source_context as source, partial.open("wb") as target:
        lines = source.iter_lines(chunk_size=65536) if isinstance(source, requests.Response) else source
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if not valid_record(record):
                skipped += 1
                continue
            encoded = (json.dumps(record, ensure_ascii=False) + "\n").encode()
            target.write(encoded)
            digest.update(encoded)
            count += 1
            if args.mode == "smoke" and count == 64:
                break
    if count < 2:
        raise RuntimeError("Fewer than two valid training examples.")
    partial.replace(output)
except BaseException:
    partial.unlink(missing_ok=True)
    raise

model_path = snapshot_download(
    model_id, revision=model_revision,
    allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken"],
    max_workers=2,
)
if source_manifest_path.is_file():
    source_metadata = json.loads(source_manifest_path.read_text())
manifest = {
    "dataset_id": dataset_id, "dataset_revision": dataset_revision,
    "dataset_filename": filename, "prepared_file": str(output),
    "source_file": str(source_path) if source_path.is_file() else None,
    "source_sha256": source_metadata["sha256"] if source_metadata else None,
    "rows": count, "skipped_rows": skipped, "sha256": digest.hexdigest(),
    "model_id": model_id, "model_revision": model_revision, "model_path": model_path,
}
manifest_dir = root / "manifests"
manifest_dir.mkdir(parents=True, exist_ok=True)
(manifest_dir / "assets.json").write_text(json.dumps(manifest, indent=2) + "\n")
(manifest_dir / (args.mode + "-assets.json")).write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2), flush=True)
