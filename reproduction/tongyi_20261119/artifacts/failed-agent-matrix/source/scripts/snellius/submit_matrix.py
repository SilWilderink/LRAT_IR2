"""Submit E5/Qwen x WebExplorer/AgentCPM x InfoSeek/BrowseComp (eight trials)."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

AGENTS = {
    "webexplorer": {"model": "hkust-nlp/WebExplorer-8B", "revision": "c7296358b988ffa5d47679f0d6fc165bfd19243a",
                    "prompt_source": "search_agent/webexplorer_utils/react_agent.py"},
    "agentcpm": {"model": "openbmb/AgentCPM-Explore", "revision": "f528bbb55317bd291387ba3347551dd3414e698e",
                 "prompt_source": "search_agent/webexplorer_utils/react_agent.py"},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    scratch = Path(os.environ["LRAT_SCRATCH_ROOT"])
    archive = Path('/home') / os.environ['USER'] / 'lrat-results/tongyi-browsecomp-plus-20261108'
    hashes = {r['path']: r['sha256'] for r in json.loads((archive/'archive-manifest.json').read_text())['files']}
    base = scratch/'evaluation'
    sources = {
        ('qwen','browsecomp'):base/'tongyi-trained-28880868',
        ('e5','browsecomp'):base/'e5-large-tongyi-20261104T204422Z',
        ('qwen','infoseek'):base/'infoseek-tongyi-20261108T205501Z/qwen',
        ('e5','infoseek'):base/'infoseek-tongyi-20261108T205501Z/e5',
    }
    root = base / ('agent-matrix-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    config = {'agents':AGENTS, 'trials':{}, 'training_provenance':'Existing LRAT-Train fine-tuned retrievers; no new seed generation or training'}
    for agent,spec in AGENTS.items():
        for retriever,dirname in [('qwen','qwen3-embedding-0.6b-lrat'),('e5','multilingual-e5-large-instruct-lrat')]:
            for benchmark in ['infoseek','browsecomp']:
                source = sources[retriever,benchmark]
                assets = json.loads((source/'assets.json').read_text())
                manifest = json.loads((source/'index/manifest.json').read_text())
                if not (source/'index/index.faiss').is_file():
                    raise RuntimeError('Missing reused index: '+str(source))
                assets.update(trained_model=str(archive/dirname/'model'),
                              model_sha256=hashes[dirname+'/model/model.safetensors'],
                              retrieval=manifest['retrieval'], agent_name=spec['model'],
                              agent_prompt=spec['prompt_source'], answer_mode='plain_or_tagged',
                              servers={'agent':{'gpus':2,'max_model_len':120000},
                                       'judge':{'gpus':4,'max_model_len':32768}})
                assets['revisions']['agent'] = [spec['model'],spec['revision']]
                assets.pop('agent_path',None)
                if benchmark=='browsecomp':
                    assets.update(benchmark='BrowseComp-Plus',question_count=830,questions_file='browsecomp-plus.tsv')
                key=f'{agent}-{retriever}-{benchmark}'
                config['trials'][key]={'agent':agent,'retriever':retriever,'benchmark':benchmark,
                                      'index':str(source/'index'),'assets':assets,
                                      'agent_hours':24 if benchmark=='infoseek' else 48,
                                      'judge_hours':3 if benchmark=='infoseek' else 6}
    print(json.dumps({'root':str(root),'trials':{k:{'agent_hours':v['agent_hours'],'judge_hours':v['judge_hours'],'index':v['index']} for k,v in config['trials'].items()}},indent=2),flush=True)
    if not args.submit:
        return
    root.mkdir(parents=True,exist_ok=False)
    snapshot=root/'source'
    files=list((repo/'scripts/snellius').glob('*.py'))+list((repo/'scripts/snellius').glob('*.sbatch'))
    files += [repo/'scripts/snellius'/n for n in ['env.sh','eval_env.sh']]
    files += [repo/p for p in ['search_agent/webexplorer_utils/react_agent.py','search_agent/tongyi_utils/react_agent.py',
                               'scripts_evaluation/evaluate.py','environments/snellius-eval/pyproject.toml',
                               'environments/snellius-eval/uv.lock']]
    for p in files:
        dest=snapshot/p.relative_to(repo)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
    (snapshot/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(snapshot))+'\n'
                                             for p in sorted(snapshot.rglob('*')) if p.is_file()))
    (root/'configuration.json').write_text(json.dumps(config,indent=2)+'\n')
    record={'root':str(root),'source':str(snapshot),'setup_job':None,'trials':{}}
    def save():
        path=root/'submitted-jobs.json'
        temp=path.with_suffix('.partial')
        temp.write_text(json.dumps(record,indent=2)+'\n');temp.replace(path)
    env=dict(os.environ,LRAT_REPO_ROOT=str(snapshot),LRAT_MATRIX_ROOT=str(root),
             LRAT_MATRIX_ARCHIVE=str(archive.parent/root.name))
    def submit(label,script,variables,resources=(),dependency=None,arguments=()):
        cmd=['sbatch','--parsable','--account='+env['LRAT_ACCOUNT'],'--chdir='+str(snapshot),'--export=ALL',
             '--job-name=lrat-'+label,'--output='+str(scratch/'logs'/(label+'-%j.out'))]
        if dependency:cmd+=['--dependency=afterok:'+dependency,'--kill-on-invalid-dep=yes']
        cmd+=list(resources)+[str(snapshot/'scripts/snellius'/script)]+list(arguments)
        job=subprocess.run(cmd,env={**env,**variables},check=True,capture_output=True,text=True).stdout.strip().split(';')[0]
        print(label,job,flush=True)
        return job
    record['setup_job']=submit('matrix-setup','matrix_prepare.sbatch',{})
    save()
    for key,trial in config['trials'].items():
        out=root/key;out.mkdir()
        variables={'LRAT_EVAL_ROOT':str(out),'LRAT_EVAL_ASSETS':str(out/'assets.json'),
                   'LRAT_EVAL_INDEX':trial['index'],'LRAT_EVAL_CONCURRENCY':'8'}
        agentjob=submit(key+'-agent','matrix_eval.sbatch',variables,
                        ['--gpus=2','--cpus-per-task=36','--mem=220G',f"--time={trial['agent_hours']}:00:00"],
                        record['setup_job'],['agent'])
        record['trials'][key]={'agent_job':agentjob,'judge_job':None,'output':str(out)};save()
        judgejob=submit(key+'-judge','matrix_eval.sbatch',variables,
                        ['--gpus=4','--cpus-per-task=72','--mem=440G',f"--time={trial['judge_hours']}:00:00"],
                        agentjob,['judge'])
        record['trials'][key]['judge_job']=judgejob;save()
    print('Submitted eight independent trials. Record:',root/'submitted-jobs.json',flush=True)


if __name__ == '__main__':
    main()
