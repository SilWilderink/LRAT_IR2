"""Submit shared Wiki preparation and two independent trained-model InfoSeek jobs."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime,timezone
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--submit",action="store_true")
args=parser.parse_args()
repo=Path(__file__).resolve().parents[2]
scratch=Path(os.environ["LRAT_SCRATCH_ROOT"])
archive=Path('/home')/os.environ['USER']/"lrat-results/tongyi-browsecomp-plus-20261108"
manifest=json.loads((archive/"archive-manifest.json").read_text())
hashes={row['path']:row['sha256'] for row in manifest['files']}
root=scratch/"evaluation"/("infoseek-tongyi-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
questions=repo/"datasets/InfoSeek-Eval.tsv"
rows=list(csv.reader(questions.open(),delimiter="\t",quoting=csv.QUOTE_NONE))
if len(rows)!=300 or len({row[0] for row in rows})!=300:raise SystemExit("Invalid InfoSeek query file")
config={"questions_sha256":hashlib.sha256(questions.read_bytes()).hexdigest(),"experiments":{}}
for name,directory in [('qwen','qwen3-embedding-0.6b-lrat'),('e5','multilingual-e5-large-instruct-lrat')]:
    model=archive/directory/"model"
    if not (model/'model.safetensors').is_file():raise SystemExit("Archived model missing: "+str(model))
    config['experiments'][name]={"model":str(model),"model_sha256":hashes[directory+'/model/model.safetensors']}
print(json.dumps({'root':str(root),**config},indent=2),flush=True)
if not args.submit:raise SystemExit(0)
root.mkdir(parents=True,exist_ok=False)
(root/"configuration.json").write_text(json.dumps(config,indent=2)+'\n')
env=dict(os.environ,LRAT_REPO_ROOT=str(repo),LRAT_INFOSEEK_ROOT=str(root))
record={"root":str(root),"configuration":config,"jobs":{}}
record_path=root/"submitted-jobs.json"
def submit(name,script,variables,dependency=None):
    jobenv={**env,**variables}
    command=['sbatch','--parsable','--account='+env['LRAT_ACCOUNT'],'--chdir='+str(repo),
             '--export=ALL','--job-name=lrat-infoseek-'+name,
             '--output='+str(scratch/'logs'/('infoseek-'+name+'-%j.out'))]
    if dependency:command+=['--dependency=afterok:'+dependency,'--kill-on-invalid-dep=yes']
    command.append(str(repo/'scripts/snellius'/script))
    result=subprocess.run(command,env=jobenv,check=True,capture_output=True,text=True)
    job=result.stdout.strip().split(';')[0]
    record['jobs'][name]=job
    record_path.write_text(json.dumps(record,indent=2)+'\n')
    print(name,job,flush=True)
    return job
setup=submit('setup','infoseek_prepare.sbatch',{})
for name,experiment in config['experiments'].items():
    evaluation=root/name;evaluation.mkdir(exist_ok=True)
    job=submit(name,'infoseek_eval.sbatch',{'LRAT_EVAL_MODEL':experiment['model'],'LRAT_EVAL_ROOT':str(evaluation),
           'LRAT_EVAL_ASSETS':str(evaluation/'assets.json'),'LRAT_EVAL_INDEX':str(evaluation/'index'),
           'LRAT_EVAL_LABEL':'lrat-infoseek-'+name},setup)
    (evaluation/'full-job.json').write_text(json.dumps({'job_id':job,'includes_indexing':True,'walltime_hours':72,'preparation_job':setup},indent=2)+'\n')
print('Pipeline record:',record_path,flush=True)
