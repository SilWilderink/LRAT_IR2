"""Preserve completed models and benchmark evidence in a verified home archive."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


EXPERIMENTS = [
    {"name": "qwen3-embedding-0.6b-lrat", "label": "Qwen3-Embedding-0.6B + LRAT",
     "run": "full-28880868", "evaluation": "tongyi-trained-28880868",
     "training_job": "28880868", "evaluation_job": "28913295", "batch": 2, "group": 2},
    {"name": "multilingual-e5-large-instruct-lrat", "label": "Multilingual-E5-Large-Instruct + LRAT",
     "run": "e5-large-tongyi-20261104T204422Z", "evaluation": "e5-large-tongyi-20261104T204422Z",
     "training_job": "28906907", "evaluation_job": "28929763", "batch": 32, "group": 10},
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Submit archive_results.sbatch through Slurm")
    os.umask(0o077)
    destination = args.destination.expanduser().resolve()
    scratch = Path(os.environ["LRAT_SCRATCH_ROOT"])
    if destination.exists():
        raise SystemExit("Archive destination already exists; refusing to overwrite: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = destination.with_name(destination.name + ".partial-" + os.environ["SLURM_JOB_ID"])
    pending.mkdir(exist_ok=False)
    files = []

    def copy_verified(source, relative):
        output = pending / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with source.open("rb") as src, output.open("xb") as dst:
            while chunk := src.read(8 * 1024 * 1024):
                digest.update(chunk)
                dst.write(chunk)
        expected = digest.hexdigest()
        if source.stat().st_size != output.stat().st_size or sha256(output) != expected:
            raise RuntimeError("Copy verification failed: " + str(source))
        files.append({"path":str(relative), "source":str(source),
                      "bytes":output.stat().st_size, "sha256":expected})

    def generated(relative, content):
        output = pending / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
        files.append({"path":str(relative), "source":"generated from archived provenance",
                      "bytes":output.stat().st_size, "sha256":sha256(output)})

    summary = []
    with tempfile.TemporaryDirectory(prefix="lrat-archive-", dir=os.environ["TMPDIR"]) as temporary:
        temporary = Path(temporary)
        for experiment in EXPERIMENTS:
            print("Archiving", experiment["name"], flush=True)
            run = scratch / "runs" / experiment["run"]
            evaluation = scratch / "evaluation" / experiment["evaluation"]
            result = json.loads((evaluation / "full-results.json").read_text())
            details = result["details"]
            ids = {row["query_id"] for row in details}
            if result["queries"] != 830 or len(details) != 830 or len(ids) != 830:
                raise RuntimeError("Full evaluation is incomplete")
            base = Path(experiment["name"])
            model = run / "model"
            if not (model / "config.json").is_file() or not list(model.glob("*.safetensors")):
                raise RuntimeError("Final model/config missing: " + str(model))
            # Final deployable encoder and tokenizer; optimizer checkpoints remain on scratch.
            for source in sorted(model.iterdir()):
                if source.is_file():
                    copy_verified(source, base / "model" / source.name)
            for source in sorted(run.iterdir()):
                if source.is_file():
                    copy_verified(source, base / "provenance" / source.name)
            states = sorted(model.glob("checkpoint-*/trainer_state.json"),
                            key=lambda p:int(p.parent.name.split("-")[-1]))
            if states:
                copy_verified(states[-1], base / "provenance/final-trainer-state.json")
            for source in sorted(evaluation.iterdir()):
                if source.is_file() and source.suffix in (".json", ".txt", ".log"):
                    copy_verified(source, base / "evaluation" / source.name)
            if (evaluation / "index/manifest.json").is_file():
                copy_verified(evaluation / "index/manifest.json", base / "evaluation/index-manifest.json")
            # Preserve exact per-question evidence and executed evaluation code compactly.
            for name in ("trajectories", "judgments", "source"):
                directory = evaluation / name
                if name in ("trajectories", "judgments"):
                    records = list(directory.glob("*.json"))
                    if len(records) != 830:
                        raise RuntimeError("Incomplete " + name)
                pack = temporary / (experiment["name"] + "-" + name + ".tar.gz")
                with tarfile.open(pack, "w:gz", compresslevel=3) as tar:
                    tar.add(directory, arcname=name)
                # Read every compressed member before preserving the pack.
                members = 0
                with tarfile.open(pack, "r:gz") as tar:
                    for member in tar:
                        if member.isfile():
                            members += 1
                            with tar.extractfile(member) as stream:
                                while stream.read(1024 * 1024):
                                    pass
                if name in ("trajectories", "judgments") and members != 830:
                    raise RuntimeError("Archive member-count mismatch: " + name)
                copy_verified(pack, base / "evaluation" / (name + ".tar.gz"))
                pack.unlink()
            retrieval = result["protocol"]["retriever"]
            generated(base / "retrieval.json", json.dumps(retrieval, indent=2) + "\n")
            metrics = result["metrics"]
            row = {**experiment, "questions":830, "correct":sum(bool(x["correct"]) for x in details),
                   "metrics":metrics, "model_path":str(destination / base / "model"),
                   "results_path":str(destination / base / "evaluation/full-results.json")}
            summary.append(row)
            print("Verified model, report, and 830 trajectories/judgments:", experiment["name"], flush=True)

    generated(Path("summary.json"), json.dumps(summary, indent=2) + "\n")
    table = ["# Completed LRAT experiments", "", "Agent: Tongyi-DeepResearch-30B-A3B. Benchmark: BrowseComp-Plus, 830 questions each.", "",
             "| Retriever | Correct | Success rate | Evidence recall | Avg. tool steps | Avg. model calls | Any evidence hit | Train batch/group |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in summary:
        m = row["metrics"]
        table.append(f"| {row['label']} | {row['correct']}/830 | {100*m['Success Rate']:.2f}% | {100*m['Evidence Recall']:.2f}% | {m['Avg Steps']:.2f} | {m['Avg Model Calls']:.2f} | {100*m['Any Evidence Hit Rate']:.2f}% | {row['batch']}/{row['group']} |")
    table += ["", "Both retrievers completed two epochs on 96,503 prepared LRAT-Train examples.",
              "Training configurations differ, so these runs are not a controlled backbone comparison.",
              "Base-retriever baselines remain deferred; no baseline improvement is established.", "",
              "Each experiment contains a standalone model/ directory (weights, config, tokenizer),",
              "evaluation/full-results.json, and provenance/. Per-question trajectories and judgments",
              "are preserved as evaluation/trajectories.tar.gz and evaluation/judgments.tar.gz.",
              "The executed evaluation-code snapshots are in evaluation/source.tar.gz.", "",
              "Load the archived model with Transformers AutoModel/AutoTokenizer and use retrieval.json",
              "for pooling, padding, normalization, input lengths and the query instruction.",
              "Qwen uses normalized last-token pooling; E5 uses normalized masked mean pooling.",
              "Original scratch paths in reports/provenance are retained unchanged as execution history.",
              "The model_path/results_path fields in summary.json point to the permanent copies.", "",
              "Training optimizer checkpoints, indexes, corpus working copies, environments and agent/judge",
              "model downloads are outside this archive. Canonical datasets remain in permanent storage.", "",
              "SHA256SUMS and archive-manifest.json record the preserved file checksums.", ""]
    generated(Path("SUMMARY.md"), "\n".join(table))
    provenance = {
        "created_utc":datetime.now(timezone.utc).isoformat(), "slurm_job":os.environ["SLURM_JOB_ID"],
        "destination":str(destination), "verification":"Every copied file matched its streaming-source SHA-256 and size; compressed audit packs were read completely.",
        "files":files, "total_file_bytes":sum(item["bytes"] for item in files),
    }
    (pending / "archive-manifest.json").write_text(json.dumps(provenance, indent=2)+"\n")
    checksums = [item["sha256"] + "  " + item["path"] for item in files]
    checksums.append(sha256(pending / "archive-manifest.json") + "  archive-manifest.json")
    (pending / "SHA256SUMS").write_text("\n".join(checksums)+"\n")
    pending.rename(destination)
    print("ARCHIVE COMPLETE", destination, flush=True)
    print("Files:",len(files),"Total GiB:",round(provenance["total_file_bytes"]/1024**3,3),flush=True)


if __name__ == "__main__":
    main()
