"""Download canonical benchmark data permanently and model snapshots to scratch."""
import csv
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import snapshot_download

REVISIONS = {
    "corpus": ("Tevatron/browsecomp-plus-corpus", "b27b02bc3e45511b8b82a13e6f90ce761df726f6"),
    "agent": ("Alibaba-NLP/Tongyi-DeepResearch-30B-A3B", "4b0ac5767427a55d08a254f0367e2934976598e0"),
    "judge": ("Qwen/Qwen3-30B-A3B-Thinking-2507", "144afc2f379b542fdd4e85a1fcd5e1f79112d95d"),
}
if not os.environ.get("SLURM_JOB_ID"):
    raise SystemExit("Use the Slurm evaluation setup job.")
started = time.monotonic()
repo = Path(os.environ["LRAT_REPO_ROOT"])
root = Path(os.environ["LRAT_EVAL_ROOT"])
root.mkdir(parents=True, exist_ok=True)
data_root = Path(os.environ["LRAT_DATA_ROOT"]) / "BrowseComp-Plus"
corpus_id, revision = REVISIONS["corpus"]
permanent = data_root / revision
permanent.mkdir(parents=True, exist_ok=True)
print("Downloading pinned corpus into permanent storage:", permanent, flush=True)
snapshot_download(corpus_id, repo_type="dataset", revision=revision,
                  local_dir=permanent, allow_patterns=["data/*.parquet", "README.md"], max_workers=2)
# Canonical queries/qrels are versioned small files in the checkout; also preserve
# the exact copies used for this benchmark beside its permanent corpus.
protocol_dir = permanent / "protocol"
protocol_dir.mkdir(exist_ok=True)
for relative in ["datasets/browsecomp-plus.tsv", "topics-qrels/queries.tsv",
                 "topics-qrels/qrel_evidence.txt", "topics-qrels/qrel_golds.txt"]:
    target = protocol_dir / Path(relative).name
    content = (repo / relative).read_bytes()
    if target.exists() and target.read_bytes() != content:
        raise RuntimeError("Pinned benchmark protocol changed: " + str(target))
    target.write_bytes(content)

db_path = root / "corpus.sqlite"
temporary = root / "corpus.building.sqlite"
temporary.unlink(missing_ok=True)
connection = sqlite3.connect(temporary)
connection.execute("CREATE TABLE documents (docid TEXT PRIMARY KEY, text TEXT NOT NULL)")
ids = set()
total = 0
for file in sorted((permanent / "data").glob("*.parquet")):
    parquet = pq.ParquetFile(file)
    for batch in parquet.iter_batches(batch_size=128, columns=["docid", "text"]):
        rows = [(str(x["docid"]), x["text"]) for x in batch.to_pylist()]
        connection.executemany("INSERT INTO documents VALUES (?, ?)", rows)
        ids.update(docid for docid, _ in rows)
        total += len(rows)
    connection.commit()
if total != 100195:
    raise RuntimeError(f"Expected 100195 documents, got {total}")
connection.close()
temporary.replace(db_path)

with (protocol_dir / "browsecomp-plus.tsv").open(newline="") as file:
    questions = list(csv.reader(file, delimiter="\t", quoting=csv.QUOTE_NONE))
question_ids = {row[0] for row in questions}
if len(questions) != 830 or len(question_ids) != 830:
    raise RuntimeError("Expected 830 unique benchmark questions")
for filename in ["qrel_evidence.txt", "qrel_golds.txt"]:
    with (protocol_dir / filename).open() as file:
        for line in file:
            qid, _, docid, relevance = line.split()
            if qid not in question_ids or docid not in ids:
                raise RuntimeError("Unmatched qrel ID in " + filename)

assets = {"corpus_path": str(permanent), "corpus_database": str(db_path),
          "corpus_count": total, "protocol_path": str(protocol_dir),
          "trained_model": os.environ["LRAT_EVAL_MODEL"], "revisions": REVISIONS}
for role in ["agent", "judge"]:
    model_id, rev = REVISIONS[role]
    print("Downloading", role, model_id, flush=True)
    assets[role + "_path"] = snapshot_download(
        model_id, revision=rev, max_workers=2,
        allow_patterns=["*.safetensors", "*.json", "*.txt", "*.model", "*.jinja"],
        ignore_patterns=["config_1m.json"],
    )
assets["protocol_sha256"] = {
    name: hashlib.sha256((protocol_dir / name).read_bytes()).hexdigest()
    for name in ["browsecomp-plus.tsv", "queries.tsv", "qrel_evidence.txt", "qrel_golds.txt"]
}
assets["setup_seconds"] = time.monotonic() - started
output = Path(os.environ["LRAT_EVAL_ASSETS"])
output.write_text(json.dumps(assets, indent=2) + "\n")
(root / "assets.json").write_text(json.dumps(assets, indent=2) + "\n")
print(json.dumps(assets, indent=2), flush=True)
