"""Run one dependent stage of the eight-trial agent evaluation matrix."""
import argparse
import json
import os
from pathlib import Path
from eval_agent import atomic_json
from eval_run import serve_and_run
from preserve_evaluation import preserve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["agent", "judge"])
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Run with Slurm")
    root = Path(os.environ["LRAT_EVAL_ROOT"])
    assets = json.loads(Path(os.environ["LRAT_EVAL_ASSETS"]).read_text())
    if not (Path(os.environ["LRAT_EVAL_INDEX"]) / "index.faiss").is_file():
        raise RuntimeError("Shared retrieval index missing")
    startup = serve_and_run(args.role, "full", assets, root)
    atomic_json(root / (args.role + "-stage.json"), {
        "job_id": os.environ["SLURM_JOB_ID"], "role": args.role,
        "server_startup_seconds": startup, "source": os.environ["LRAT_REPO_ROOT"],
        "status": "completed",
    })
    if args.role == "judge":
        preserve(root, Path(os.environ["LRAT_MATRIX_ARCHIVE"]) / root.name,
                 source=Path(os.environ["LRAT_REPO_ROOT"]))


if __name__ == "__main__":
    main()
