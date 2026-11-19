"""Manage local model servers, timing pilot, and trained-model evaluation."""
import argparse
import json
import math
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests

from eval_agent import atomic_json


def terminate(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def serve_and_run(role, mode, assets, root):
    settings = assets.get("servers", {}).get(role, {})
    alias = "lrat-eval-" + role
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log_path = root / (mode + "-" + role + "-server.log")
    command = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", assets[role + "_path"], "--served-model-name", alias,
        "--host", "127.0.0.1", "--port", str(port), "--tensor-parallel-size", str(settings.get("gpus", 4)),
        "--dtype", "bfloat16", "--gpu-memory-utilization", "0.85",
        "--max-model-len", str(settings.get("max_model_len", 120000 if role == "agent" else 32768)),
        "--max-num-seqs", os.environ.get("LRAT_EVAL_CONCURRENCY", "8"),
        "--max-num-batched-tokens", "8192", "--enable-chunked-prefill",
        "--enable-prefix-caching",
        "--enforce-eager", "--generation-config", "vllm",
        "--seed", "2025", "--disable-log-requests",
    ]
    print("Starting", role, "server; log:", log_path, flush=True)
    started = time.monotonic()
    with log_path.open("a") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(role + " server failed; inspect " + str(log_path))
                try:
                    if requests.get(f"http://127.0.0.1:{port}/health", timeout=5).ok:
                        break
                except requests.RequestException:
                    pass
                time.sleep(5)
            else:
                raise RuntimeError(role + " server did not become ready within 30 minutes")
            startup_seconds = time.monotonic() - started
            subprocess.run(
                [sys.executable, str(Path(__file__).with_name("eval_agent.py")), role, mode, "--port", str(port)],
                check=True,
            )
            return startup_seconds
        finally:
            terminate(process)
            # Allow spawned workers to release device memory before the next model.
            time.sleep(10)


def submit_full(root, assets):
    pilot_agent = json.loads((root / "pilot-agent-timing.json").read_text())
    pilot_judge = json.loads((root / "pilot-judge-timing.json").read_text())
    server = json.loads((root / "pilot-server-timing.json").read_text())
    if pilot_agent["errors"] or pilot_judge["errors"]:
        raise RuntimeError("Pilot has infrastructure failures; full evaluation will not be submitted")
    n_agent = pilot_agent["new_queries"]
    n_judge = pilot_judge["new_queries"]
    if min(n_agent, n_judge) <= 0:
        raise RuntimeError("No measured pilot throughput available")
    remaining = assets.get("question_count", 830) - int(os.environ.get("LRAT_EVAL_PILOT_SIZE", "16"))
    projected_agent = pilot_agent["seconds"] / n_agent * remaining
    projected_judge = pilot_judge["seconds"] / n_judge * remaining
    startup = sum(server.values()) + pilot_agent.get("client_setup_seconds", 0) + pilot_judge.get("client_setup_seconds", 0)
    point = projected_agent + projected_judge + startup
    allocated_hours = max(4, math.ceil((point * 1.6 + 1800) / 3600))
    if allocated_hours > 120:
        raise RuntimeError("Measured estimate exceeds the partition maximum; split evaluation into shards")
    estimate = {
        "remaining_questions": remaining, "pilot_questions": n_agent,
        "agent_projected_hours": projected_agent / 3600,
        "judge_projected_hours": projected_judge / 3600,
        "server_startup_hours": startup / 3600,
        "point_estimate_hours": point / 3600,
        "planning_range_hours": [point * 0.75 / 3600, point * 1.6 / 3600],
        "slurm_walltime_hours": allocated_hours,
        "gpus": 4, "queue_wait_included": False,
        "note": "16-query throughput extrapolation; planning range is not a statistical confidence interval.",
    }
    atomic_json(root / "runtime-estimate.json", estimate)
    if (root / "full-job.json").exists():
        print("Full evaluation job already recorded; not submitting a duplicate.", flush=True)
        return
    repo = Path(os.environ["LRAT_REPO_ROOT"])
    label = os.environ.get("LRAT_EVAL_LABEL", "lrat-eval")
    output = Path(os.environ["LRAT_SCRATCH_ROOT"]) / ("logs/" + label + "-full-%j.out")
    command = ["sbatch", "--parsable", "--job-name=" + label + "-full",
               "--account=" + os.environ["LRAT_ACCOUNT"], "--chdir=" + str(repo),
               "--export=ALL", f"--time={allocated_hours}:00:00", "--output=" + str(output),
               str(repo / "scripts/snellius/eval_run.sbatch"), "full"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    job_id = result.stdout.strip().split(";")[0]
    atomic_json(root / "full-job.json", {"job_id": job_id, "estimate": estimate})
    print("Full trained-model evaluation submitted:", job_id, flush=True)
    print(json.dumps(estimate, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["pilot", "full"])
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Run through Slurm.")
    root = Path(os.environ["LRAT_EVAL_ROOT"])
    assets = json.loads(Path(os.environ["LRAT_EVAL_ASSETS"]).read_text())
    # Keep the exact implementation used by each allocation alongside its audit.
    repo = Path(os.environ["LRAT_REPO_ROOT"])
    snapshot = root / "source" / (args.mode + "-" + os.environ["SLURM_JOB_ID"])
    snapshot.mkdir(parents=True, exist_ok=True)
    source_files = list((repo / "scripts/snellius").glob("eval_*.py"))
    source_files += list((repo / "scripts/snellius").glob("infoseek_*.py"))
    source_files += list((repo / "scripts/snellius").glob("infoseek_*.sbatch"))
    source_files += list((repo / "scripts/snellius").glob("eval_*.sbatch"))
    source_files += [repo / "scripts/snellius/eval_env.sh",
                     repo / "environments/snellius-eval/pyproject.toml",
                     repo / "environments/snellius-eval/uv.lock"]
    for source in source_files:
        destination = snapshot / source.relative_to(repo)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    server_timing = {}
    for role in ("agent", "judge"):
        server_timing[role] = serve_and_run(role, args.mode, assets, root)
    atomic_json(root / (args.mode + "-server-timing.json"), server_timing)
    if args.mode == "pilot":
        submit_full(root, assets)
    print("Completed trained-model evaluation stage:", args.mode, flush=True)


if __name__ == "__main__":
    main()
