"""Checkpointed four-GPU Wiki encoding and exact FAISS index assembly."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import faiss
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer
from eval_embedding import retrieval_settings, pool_embeddings


def partition(count, rank, world):
    if count < 0 or world < 1 or not 0 <= rank < world:
        raise ValueError("Invalid corpus partition")
    start = count * rank // world
    return start, count * (rank+1) // world


def atomic_json(path, value):
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, indent=2)+"\n")
    partial.replace(path)


def fingerprint(assets, world):
    settings = {"model_sha256":assets["model_sha256"],"corpus_sha256":assets["corpus_sha256"],
                "count":assets["corpus_count"],"retrieval":retrieval_settings(assets),"world":world}
    return hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()


def complete(assets, root, world):
    manifest = root / "manifest.json"
    if not manifest.exists(): return False
    previous = json.loads(manifest.read_text())
    if previous["fingerprint"] != fingerprint(assets,world):
        raise RuntimeError("Existing Wiki index belongs to a different model/corpus/protocol")
    return ((root/"index.faiss").is_file() and (root/"docids.i64").is_file()
            and (root/"docids.i64").stat().st_size == assets["corpus_count"]*8)


def encode(assets, root, rank, world):
    if complete(assets,root,world):
        print("Reusing complete Wiki index",flush=True);return
    if not torch.cuda.is_available():raise RuntimeError("Slurm GPU allocation required")
    settings = retrieval_settings(assets)
    start,stop = partition(assets["corpus_count"],rank,world)
    shard = root / "shards" / str(rank)
    shard.mkdir(parents=True,exist_ok=True)
    progress_path = shard / "progress.json"
    signature = fingerprint(assets,world)
    config = json.loads((Path(assets["trained_model"])/"config.json").read_text())
    dimension = config["hidden_size"]
    path = shard / "vectors.npy"
    done = 0
    if progress_path.exists():
        previous = json.loads(progress_path.read_text())
        if previous["fingerprint"] != signature or previous["start"] != start or previous["stop"] != stop:
            raise RuntimeError("Encoding checkpoint does not match the requested shard")
        done = previous["encoded"]
        vectors = np.lib.format.open_memmap(path,mode="r+")
        if vectors.shape != (stop-start,dimension):raise RuntimeError("Shard shape mismatch")
    else:
        vectors = np.lib.format.open_memmap(path,mode="w+",dtype=np.float32,shape=(stop-start,dimension))
    if done == stop-start:
        print("Completed encoding shard already exists:",rank,flush=True);return
    tokenizer = AutoTokenizer.from_pretrained(assets["trained_model"],padding_side=settings["padding_side"],local_files_only=True)
    model = AutoModel.from_pretrained(assets["trained_model"],torch_dtype=torch.bfloat16,
                                     attn_implementation="sdpa",local_files_only=True).cuda().eval()
    connection = sqlite3.connect("file:"+assets["corpus_database"]+"?mode=ro",uri=True)
    cursor = connection.execute("SELECT text FROM documents WHERE rowid>? AND rowid<=? ORDER BY rowid",(start+done,stop))
    started = time.monotonic();initial = saved = done
    while rows := cursor.fetchmany(64):
        texts = [settings["passage_prefix"]+row[0] for row in rows]
        batch = tokenizer(texts,padding=True,truncation=True,max_length=settings["max_length"],return_tensors="pt").to("cuda")
        with torch.inference_mode():
            hidden = model(**batch).last_hidden_state
            reps = pool_embeddings(hidden,batch["attention_mask"],settings["pooling"])
            if settings["normalize"]:reps=torch.nn.functional.normalize(reps,dim=-1)
            reps = reps.cpu().numpy()
        vectors[done:done+len(rows)] = reps
        done += len(rows)
        if done-saved >= 4096 or done == stop-start:
            vectors.flush()
            elapsed = time.monotonic()-started
            atomic_json(progress_path,{"fingerprint":signature,"start":start,"stop":stop,"encoded":done,
                                       "new_documents_per_second":(done-initial)/elapsed,"seconds_this_attempt":elapsed})
            saved = done
            print(f"Shard {rank}: {done}/{stop-start} documents; {(done-initial)/elapsed:.1f} docs/s",flush=True)
    connection.close()
    if done != stop-start:raise RuntimeError("SQLite corpus ended before shard boundary")


def merge(assets, root, world):
    if complete(assets,root,world):return
    config = json.loads((Path(assets["trained_model"])/"config.json").read_text())
    signature = fingerprint(assets,world)
    index = faiss.IndexFlatIP(config["hidden_size"])
    started = time.monotonic()
    for rank in range(world):
        start,stop=partition(assets["corpus_count"],rank,world)
        shard=root/"shards"/str(rank)
        progress=json.loads((shard/"progress.json").read_text())
        if progress["fingerprint"] != signature or progress["encoded"] != stop-start:
            raise RuntimeError("Cannot merge an incomplete shard")
        vectors=np.load(shard/"vectors.npy",mmap_mode="r")
        if vectors.shape != (stop-start,config["hidden_size"]):raise RuntimeError("Shard dimensions differ")
        for offset in range(0,len(vectors),65536):
            index.add(np.ascontiguousarray(vectors[offset:offset+65536],dtype=np.float32))
        print("Merged Wiki vectors:",index.ntotal,flush=True)
    if index.ntotal != assets["corpus_count"]:raise RuntimeError("Incomplete merged index")
    partial=root/"index.building.faiss"
    faiss.write_index(index,str(partial))
    partial.replace(root/"index.faiss")
    shutil.copyfile(assets["corpus_docids"],root/"docids.i64")
    if (root/"docids.i64").stat().st_size != index.ntotal*8:raise RuntimeError("Wrong ID-map size")
    atomic_json(root/"manifest.json",{"fingerprint":signature,"documents":index.ntotal,
                 "dimension":config["hidden_size"],"model_path":assets["trained_model"],
                 "model_sha256":assets["model_sha256"],"corpus_sha256":assets["corpus_sha256"],
                 "corpus_revision":assets["revisions"]["corpus"],"retrieval":retrieval_settings(assets),
                 "docids_format":"little-endian int64","encoding_shards":world,
                 "merge_seconds":time.monotonic()-started})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["encode","merge"])
    args=parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):raise SystemExit("Use Slurm")
    root=Path(os.environ["LRAT_EVAL_INDEX"]);root.mkdir(parents=True,exist_ok=True)
    assets=json.loads(Path(os.environ["LRAT_EVAL_ASSETS"]).read_text())
    if args.mode=="encode":encode(assets,root,int(os.environ["SLURM_PROCID"]),4)
    else:merge(assets,root,4)


if __name__=="__main__":main()
