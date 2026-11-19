"""Prepare the paper-linked Wiki-25 corpus once for both InfoSeek evaluations."""
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import numpy as np
from huggingface_hub import hf_hub_download, snapshot_download
from eval_embedding import DEFAULT_RETRIEVAL, E5_RETRIEVAL

CORPUS = "Lk123/wiki-25-512"
REVISION = "fc1e312568b14385c04f41bc09157d8fa4c20658"
FILENAME = "wiki-25-512.jsonl"
SOURCE_BYTES = 18496937987
SOURCE_SHA256 = "4d795938bb89cbd7e7467a8da4e772f7ae95e6b533181aeace2a5e3fd3de6393"
ROLES = {
    "agent": ("Alibaba-NLP/Tongyi-DeepResearch-30B-A3B", "4b0ac5767427a55d08a254f0367e2934976598e0"),
    "judge": ("Qwen/Qwen3-30B-A3B-Thinking-2507", "144afc2f379b542fdd4e85a1fcd5e1f79112d95d"),
}


def atomic_json(path, data):
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def main():
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Submit infoseek_prepare.sbatch")
    started = time.monotonic()
    root = Path(os.environ["LRAT_INFOSEEK_ROOT"])
    config = json.loads((root / "configuration.json").read_text())
    repo = Path(os.environ["LRAT_REPO_ROOT"])
    permanent = Path(os.environ["LRAT_DATA_ROOT"]) / "Wiki-25-512" / REVISION
    permanent.mkdir(parents=True, exist_ok=True)
    source = permanent / FILENAME
    metadata = permanent / "source.json"
    if not source.is_file() or not metadata.is_file():
        cached = Path(hf_hub_download(CORPUS, FILENAME, repo_type="dataset", revision=REVISION))
        partial = source.with_name(FILENAME + ".copy-" + os.environ["SLURM_JOB_ID"])
        digest = hashlib.sha256()
        with cached.open("rb") as src, partial.open("wb") as dst:
            while chunk := src.read(8 * 1024 * 1024):
                digest.update(chunk)
                dst.write(chunk)
        if partial.stat().st_size != SOURCE_BYTES or digest.hexdigest() != SOURCE_SHA256:
            raise RuntimeError("Downloaded corpus differs from pinned file metadata")
        partial.replace(source)
        atomic_json(metadata, {"dataset":CORPUS,"revision":REVISION,"bytes":SOURCE_BYTES,"sha256":SOURCE_SHA256})
    existing = json.loads(metadata.read_text())
    if source.stat().st_size != SOURCE_BYTES or existing["sha256"] != SOURCE_SHA256:
        raise RuntimeError("Permanent corpus provenance mismatch")
    print("Canonical corpus ready:", source, flush=True)
    protocol = Path(os.environ["LRAT_DATA_ROOT"]) / "InfoSeek-Eval" / config["questions_sha256"]
    protocol.mkdir(parents=True, exist_ok=True)
    contents = (repo / "datasets/InfoSeek-Eval.tsv").read_bytes()
    if hashlib.sha256(contents).hexdigest() != config["questions_sha256"]:
        raise RuntimeError("InfoSeek question file changed after submission")
    question_file = protocol / "InfoSeek-Eval.tsv"
    if question_file.exists() and question_file.read_bytes() != contents:
        raise RuntimeError("Permanent InfoSeek question file differs")
    question_file.write_bytes(contents)
    with question_file.open(newline="") as file:
        questions = list(csv.reader(file, delimiter="\t", quoting=csv.QUOTE_NONE))
    if len(questions) != 300 or len({row[0] for row in questions}) != 300 or any(len(row)!=3 for row in questions):
        raise RuntimeError("Expected 300 unique question/answer triples")
    prepared = root / "corpus"
    prepared.mkdir(exist_ok=True)
    manifest_path = prepared / "manifest.json"
    database = prepared / "corpus.sqlite"
    ids = prepared / "docids.i64"
    if manifest_path.exists() and database.is_file() and ids.is_file():
        manifest = json.loads(manifest_path.read_text())
        if manifest["source_sha256"] != SOURCE_SHA256:
            raise RuntimeError("Prepared corpus revision mismatch")
        count = manifest["documents"]
    else:
        temporary = prepared / "corpus.building.sqlite"
        temporary.unlink(missing_ok=True)
        ids_temporary = prepared / "docids.building.i64"
        connection = sqlite3.connect(temporary)
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA cache_size=-65536")
        connection.execute("CREATE TABLE documents (docid TEXT PRIMARY KEY, text TEXT NOT NULL)")
        count = 0
        rows, batch_ids = [], []
        def flush(output):
            nonlocal count
            connection.executemany("INSERT INTO documents VALUES (?, ?)", rows)
            output.write(np.asarray(batch_ids,dtype="<i8").tobytes())
            count += len(rows)
            rows.clear(); batch_ids.clear()
        with source.open() as file, ids_temporary.open("wb") as output:
            for line in file:
                record = json.loads(line)
                docid, text = record["id"], record["contents"]
                if not isinstance(docid,int) or not isinstance(text,str) or not text.strip():
                    raise RuntimeError("Invalid Wiki corpus record")
                rows.append((str(docid),text));batch_ids.append(docid)
                if len(rows) == 8192:
                    flush(output)
                    if count % (8192*64) == 0:
                        print("Prepared Wiki documents:",count,flush=True)
            if rows: flush(output)
        connection.commit()
        connection.close()
        if count <= 0 or ids_temporary.stat().st_size != count*8:
            raise RuntimeError("Incomplete document ID map")
        temporary.replace(database);ids_temporary.replace(ids)
        manifest = {"dataset":CORPUS,"revision":REVISION,"source_sha256":SOURCE_SHA256,
                    "source_file":str(source),"documents":count,"schema":{"id":"int","contents":"text"},
                    "database":str(database),"docids":str(ids)}
        atomic_json(manifest_path,manifest)
    role_paths = {role:snapshot_download(model,revision=revision,max_workers=2,
                  allow_patterns=["*.safetensors","*.json","*.txt","*.model","*.jinja"],
                  ignore_patterns=["config_1m.json"]) for role,(model,revision) in ROLES.items()}
    for name, experiment in config["experiments"].items():
        evaluation = root / name
        evaluation.mkdir(exist_ok=True)
        settings = E5_RETRIEVAL if name=="e5" else DEFAULT_RETRIEVAL
        assets = {"benchmark":"InfoSeek-Eval","question_count":300,"questions_file":"InfoSeek-Eval.tsv",
                  "protocol_path":str(protocol),"questions_sha256":config["questions_sha256"],
                  "corpus_database":str(database),"corpus_count":count,"corpus_docids":str(ids),
                  "corpus_sha256":SOURCE_SHA256,"corpus_path":str(permanent),
                  "trained_model":experiment["model"],"model_sha256":experiment["model_sha256"],
                  "retrieval":settings,"revisions":{"corpus":[CORPUS,REVISION],**ROLES},
                  **{role+"_path":value for role,value in role_paths.items()}}
        atomic_json(evaluation / "assets.json",assets)
    atomic_json(root / "prepare-complete.json",{"documents":count,"seconds":time.monotonic()-started,
                                                "questions":300,"slurm_job":os.environ["SLURM_JOB_ID"]})
    print("InfoSeek assets ready:",root,"documents:",count,flush=True)


if __name__=="__main__":
    main()
