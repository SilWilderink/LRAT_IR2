"""Encode the fixed corpus with the trained retriever, retaining measured throughput."""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import faiss
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer
from eval_embedding import retrieval_settings, pool_embeddings

if not os.environ.get("SLURM_JOB_ID") or not torch.cuda.is_available():
    raise SystemExit("Run inside a Slurm GPU allocation.")
assets = json.loads(Path(os.environ["LRAT_EVAL_ASSETS"]).read_text())
settings = retrieval_settings(assets)
out = Path(os.environ["LRAT_EVAL_INDEX"])
out.mkdir(parents=True, exist_ok=True)
model_path = Path(os.environ["LRAT_EVAL_MODEL"])
config_hash = hashlib.sha256((model_path / "config.json").read_bytes()).hexdigest()
manifest_path = out / "manifest.json"
if manifest_path.exists():
    previous = json.loads(manifest_path.read_text())
    if previous["model_path"] == str(model_path) and previous["model_config_sha256"] == config_hash and previous.get("retrieval", settings) == settings and (out / "index.faiss").is_file():
        print("Reusing the trained-model corpus index.", flush=True)
        raise SystemExit(0)

tokenizer = AutoTokenizer.from_pretrained(model_path, padding_side=settings["padding_side"], local_files_only=True)
model = AutoModel.from_pretrained(model_path, torch_dtype=torch.bfloat16,
                                 attn_implementation="sdpa", local_files_only=True).cuda().eval()
connection = sqlite3.connect(assets["corpus_database"])
cursor = connection.execute("SELECT docid, text FROM documents ORDER BY rowid")
index = faiss.IndexFlatIP(model.config.hidden_size)
ids = []
started = time.monotonic()
batch_size = 64
while rows := cursor.fetchmany(batch_size):
    texts = [settings["passage_prefix"] + row[1] for row in rows]
    batch = tokenizer(texts, padding=True, truncation=True, max_length=settings["max_length"], return_tensors="pt").to("cuda")
    with torch.inference_mode():
        hidden = model(**batch).last_hidden_state
        reps = pool_embeddings(hidden, batch["attention_mask"], settings["pooling"])
        if settings["normalize"]:
            reps = torch.nn.functional.normalize(reps, p=2, dim=-1)
        reps = reps.cpu().numpy()
    index.add(np.ascontiguousarray(reps, dtype=np.float32))
    ids.extend(row[0] for row in rows)
    if len(ids) % 4096 == 0 or len(ids) == assets["corpus_count"]:
        elapsed = time.monotonic() - started
        print(f"Encoded {len(ids)}/{assets['corpus_count']} documents, {len(ids)/elapsed:.1f} docs/s", flush=True)
connection.close()
elapsed = time.monotonic() - started
if len(ids) != assets["corpus_count"]:
    raise RuntimeError("Incomplete corpus encoding")
faiss.write_index(index, str(out / "index.faiss"))
(out / "docids.json").write_text(json.dumps(ids))
manifest = {
    "model_path": str(model_path), "model_config_sha256": config_hash,
    "corpus_revision": assets["revisions"]["corpus"], "documents": len(ids),
    "seconds": elapsed, "documents_per_second": len(ids) / elapsed,
    "passage_max_length": settings["max_length"], "pooling": settings["pooling"],
    "normalize": settings["normalize"], "retrieval": settings,
}
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, indent=2), flush=True)
