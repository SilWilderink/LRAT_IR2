"""Download pinned agents and validate reused retrieval assets on staging."""
import hashlib
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download
from transformers import AutoConfig, AutoTokenizer
from eval_agent import atomic_json, load_questions, load_prompt


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        while block := f.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Run with Slurm")
    root = Path(os.environ["LRAT_MATRIX_ROOT"])
    config = json.loads((root / "configuration.json").read_text())
    paths, checked = {}, {}
    for key, spec in config["agents"].items():
        paths[key] = snapshot_download(spec["model"], revision=spec["revision"],
                                      allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja"],
                                      max_workers=2)
        model = AutoConfig.from_pretrained(paths[key], local_files_only=True)
        if model.model_type != "qwen3" or model.max_position_embeddings < 120000:
            raise RuntimeError("Unexpected agent architecture or context capacity")
        tokenizer = AutoTokenizer.from_pretrained(paths[key], local_files_only=True)
        prompt = load_prompt(os.environ["LRAT_REPO_ROOT"], spec["prompt_source"], "SYSTEM_PROMPT_SEARCH_ONLY")
        if not tokenizer.apply_chat_template([{"role":"system","content":prompt},
                                            {"role":"user","content":"test"}], tokenize=True, add_generation_prompt=True):
            raise RuntimeError("Agent chat template failed")
        print("Ready:", key, paths[key], flush=True)
    for key, trial in config["trials"].items():
        assets = trial["assets"]
        model = assets["trained_model"]
        if model not in checked:
            checked[model] = sha256(Path(model) / "model.safetensors")
        if checked[model] != assets["model_sha256"]:
            raise RuntimeError("Archived retriever checksum mismatch")
        index = Path(trial["index"])
        manifest = json.loads((index / "manifest.json").read_text())
        if manifest["documents"] != assets["corpus_count"]:
            raise RuntimeError("Index/corpus count mismatch")
        if manifest.get("model_sha256"):
            if manifest["model_sha256"] != assets["model_sha256"]:
                raise RuntimeError("InfoSeek index belongs to a different model")
        else:
            original = str(Path(manifest["model_path"]) / "model.safetensors")
            if original not in checked:
                checked[original] = sha256(original)
            if checked[original] != assets["model_sha256"]:
                raise RuntimeError("BrowseComp index model differs from archived retriever")
        if manifest["retrieval"] != assets["retrieval"]:
            raise RuntimeError("Index and query encoding settings differ")
        if not (index / "index.faiss").is_file() or not Path(assets["corpus_database"]).is_file():
            raise RuntimeError("Index or corpus database missing")
        if (index / "docids.i64").exists():
            if (index / "docids.i64").stat().st_size != manifest["documents"] * 8:
                raise RuntimeError("Wrong index ID count")
        elif len(json.loads((index / "docids.json").read_text())) != manifest["documents"]:
            raise RuntimeError("Wrong index ID count")
        rows = load_questions(assets["protocol_path"], assets["questions_file"])
        if len(rows) != assets["question_count"] or len({r[0] for r in rows}) != len(rows):
            raise RuntimeError("Wrong benchmark question count")
        for name, digest in assets.get("protocol_sha256", {}).items():
            if sha256(Path(assets["protocol_path"]) / name) != digest:
                raise RuntimeError("Benchmark protocol hash mismatch")
        if assets.get("questions_sha256") and sha256(Path(assets["protocol_path"]) / assets["questions_file"]) != assets["questions_sha256"]:
            raise RuntimeError("InfoSeek question hash mismatch")
        if not Path(assets["judge_path"]).is_dir():
            raise RuntimeError("Pinned judge cache missing")
        assets["agent_path"] = paths[trial["agent"]]
        atomic_json(root / key / "assets.json", assets)
        print("Validated:", key, flush=True)
    atomic_json(root / "preparation.json", {"status":"completed", "agents":paths, "verified_hashes":checked})


if __name__ == "__main__":
    main()
