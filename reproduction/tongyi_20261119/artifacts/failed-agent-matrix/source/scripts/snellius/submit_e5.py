"""Submit an independent E5 training -> index -> Tongyi evaluation pipeline."""
import argparse
import datetime
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--submit", action="store_true", help="Submit jobs; otherwise print configuration")
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
scratch = Path(os.environ["LRAT_SCRATCH_ROOT"])
tag = "e5-large-tongyi-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
run = scratch / "runs" / tag
evaluation = scratch / "evaluation" / tag
# Export isolated paths to every dependent job and the automatically submitted
# full evaluation. Shared immutable assets remain read-only inputs.
env = dict(os.environ)
env.update(LRAT_REPO_ROOT=str(repo), LRAT_E5_RUN_DIR=str(run),
           LRAT_E5_ASSETS=str(run / "training-assets.json"),
           LRAT_EVAL_MODEL=str(run / "model"), LRAT_EVAL_ROOT=str(evaluation),
           LRAT_EVAL_ASSETS=str(evaluation / "assets.json"),
           LRAT_EVAL_INDEX=str(evaluation / "index"), LRAT_EVAL_LABEL="lrat-e5-eval")
config = {key:value for key,value in env.items() if key.startswith("LRAT_E5_") or key.startswith("LRAT_EVAL_")}
config["training"] = {"model":"intfloat/multilingual-e5-large-instruct", "batch_size":32,
                      "group_size":10,"gpus":1,"epochs":2,"walltime_hours":48,
                      "batch_interpretation":"32 queries per optimizer step on one GPU; cross-device negatives disabled"}
print(json.dumps(config, indent=2), flush=True)
if not args.submit:
    raise SystemExit(0)
for path in (scratch/"manifests/full-assets.json", scratch/"manifests/browsecomp-assets.json",
             scratch/"data/train.jsonl"):
    if not path.is_file():
        raise SystemExit("Missing shared prerequisite: " + str(path))
run.mkdir(parents=True, exist_ok=False)
evaluation.mkdir(parents=True, exist_ok=False)
logs = scratch / "logs"
logs.mkdir(parents=True, exist_ok=True)
record = {"configuration":config,"jobs":{}}
record_path = evaluation / "submitted-jobs.json"

def submit(stage, script, dependency=None, argument=None):
    command = ["sbatch", "--parsable", "--account="+env["LRAT_ACCOUNT"],
               "--chdir="+str(repo), "--export=ALL", "--job-name=lrat-e5-"+stage,
               "--output="+str(logs/("e5-"+stage+"-%j.out"))]
    if dependency:
        command += ["--dependency=afterok:"+dependency,"--kill-on-invalid-dep=yes"]
    command.append(str(repo/"scripts/snellius"/script))
    if argument:
        command.append(argument)
    result = subprocess.run(command,env=env,check=True,capture_output=True,text=True)
    job = result.stdout.strip().split(";")[0]
    record["jobs"][stage] = job
    record_path.write_text(json.dumps(record,indent=2)+"\n")
    print(stage+": "+job,flush=True)
    return job

setup = submit("setup", "e5_setup.sbatch")
training = submit("train", "e5_train.sbatch", setup)
index = submit("index", "eval_index.sbatch", training)
submit("pilot", "eval_run.sbatch", index, "pilot")
print("Pipeline record:",record_path,flush=True)
