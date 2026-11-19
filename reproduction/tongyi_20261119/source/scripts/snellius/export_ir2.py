"""Copy the completed reproduction and final checkpoints into LRAT_IR2 via Slurm."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from preserve_evaluation import preserve

SOURCE = Path('/gpfs/home6/scur0901/LRAT')
DEST = Path('/gpfs/home6/scur0901/LRAT_IR2/reproduction/tongyi_20261119')
ARCHIVES = Path('/gpfs/home6/scur0901/lrat-results')
SCRATCH = Path('/scratch-shared/scur0901/lrat')

def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Run through Slurm')
    os.umask(0o027)
    if DEST.exists():
        raise SystemExit(f'Destination already exists: {DEST}')
    pending = DEST.with_name(DEST.name + '.partial-' + os.environ['SLURM_JOB_ID'])
    pending.mkdir(parents=True, exist_ok=False)
    records = []

    def copy(src, rel):
        out = pending / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            raise RuntimeError(f'Duplicate destination: {rel}')
        shutil.copy2(src, out)
        checksum = digest(src)
        if out.stat().st_size != src.stat().st_size or digest(out) != checksum:
            raise RuntimeError(f'Copy verification failed: {src}')
        records.append(dict(path=str(rel), source=str(src), bytes=out.stat().st_size, sha256=checksum))

    def tree(src, rel):
        for f in sorted(src.rglob('*')):
            if f.is_file() and not any(x in f.parts for x in ('__pycache__', '.git', '.venv')) and f.name != 'local.sh':
                copy(f, rel / f.relative_to(src))

    # Complete runnable source snapshot, including the modified training implementation.
    tracked = subprocess.check_output(['git', '-C', str(SOURCE), 'ls-files', '-z']).decode().split('\0')
    sources = {SOURCE / x for x in tracked if x and (SOURCE / x).is_file()}
    for folder in ('scripts', 'environments', 'docs'):
        sources.update(p for p in (SOURCE / folder).rglob('*') if p.is_file())
    sources.add(SOURCE / 'AGENTS.md')
    for f in sorted(sources):
        if '__pycache__' not in f.parts and f.name != 'local.sh':
            copy(f, Path('source') / f.relative_to(SOURCE))
    (pending / 'source-changes.patch').write_bytes(subprocess.check_output(['git', '-C', str(SOURCE), 'diff', '--binary']))
    tree(ARCHIVES / 'tongyi-browsecomp-plus-20261108', Path('artifacts/tongyi-browsecomp-plus'))
    print('Copied both deployable retrievers and BrowseComp-Plus evidence', flush=True)
    tree(ARCHIVES / 'tongyi-infoseek-20261111/qwen3-embedding-0.6b-lrat', Path('artifacts/tongyi-infoseek/qwen3-embedding-0.6b-lrat'))
    e5 = SCRATCH / 'evaluation/infoseek-tongyi-20261108T205501Z/e5'
    out = pending / 'artifacts/tongyi-infoseek/multilingual-e5-large-instruct-lrat'
    preserve(e5, out, source=e5 / 'source')
    for f in sorted(e5.glob('*.log')):
        copy(f, out.relative_to(pending) / f.name)
    copy(e5 / 'index/manifest.json', out.relative_to(pending) / 'index-manifest.json')
    tree(ARCHIVES / 'browse-audit-20261111', Path('artifacts/browse-audit'))
    for name, run, step in [('qwen3-embedding-0.6b-lrat', 'full-28880868', '96502'),
                            ('multilingual-e5-large-instruct-lrat', 'e5-large-tongyi-20261104T204422Z', '6030')]:
        tree(SCRATCH / 'runs' / run / 'model' / ('checkpoint-' + step), Path('artifacts/training-checkpoints') / name / ('checkpoint-' + step))
        print('Copied full final checkpoint:', name, flush=True)
    matrix = SCRATCH / 'evaluation/agent-matrix-20261111T122431Z'
    tree(matrix, Path('artifacts/failed-agent-matrix'))
    for f in sorted((SCRATCH / 'logs').glob('*291225*.out')):
        copy(f, Path('artifacts/failed-agent-matrix/slurm-logs') / f.name)
    summary = []
    for model in ('qwen3-embedding-0.6b-lrat', 'multilingual-e5-large-instruct-lrat'):
        for benchmark, relative in [('BrowseComp-Plus', Path('artifacts/tongyi-browsecomp-plus') / model / 'evaluation/full-results.json'),
                                    ('InfoSeek-Eval', Path('artifacts/tongyi-infoseek') / model / 'full-results.json')]:
            result = json.loads((pending / relative).read_text())
            expected = 830 if benchmark == 'BrowseComp-Plus' else 300
            if result['queries'] != expected or len({r['query_id'] for r in result['details']}) != expected:
                raise RuntimeError(f'Incomplete results: {relative}')
            summary.append(dict(retriever=model, benchmark=benchmark, correct=sum(bool(x['correct']) for x in result['details']), queries=expected, metrics=result['metrics'], report=str(relative), model=f'artifacts/tongyi-browsecomp-plus/{model}/model'))
    (pending / 'results-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (pending / '.gitignore').write_text('# Large local model/resume artifacts: paths and hashes are tracked in manifest.json.\n*.safetensors\noptimizer.pt\n*.pth\n*.bin\n__pycache__/\nlocal.sh\n')
    for filename in ('README.md', 'job-status.txt'):
        copy(SOURCE / 'scripts/snellius/ir2_export_metadata' / filename, Path(filename))
    provenance = dict(created_utc=datetime.now(timezone.utc).isoformat(), slurm_job=os.environ['SLURM_JOB_ID'], source_commit=subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(), source_repository=str(SOURCE), destination=str(DEST), branch='Reproduction_results', verified_copies=records)
    # Include generated packs as well as copied artifacts in the final integrity manifest.
    provenance['files'] = [dict(path=str(p.relative_to(pending)), bytes=p.stat().st_size, sha256=digest(p)) for p in sorted(pending.rglob('*')) if p.is_file()]
    (pending / 'manifest.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (pending / 'SHA256SUMS').write_text(''.join(f"{item['sha256']}  {item['path']}\n" for item in provenance['files']) + digest(pending / 'manifest.json') + '  manifest.json\n')
    pending.rename(DEST)
    print('EXPORT COMPLETE', DEST, 'files', len(provenance['files']), 'GiB', round(sum(x['bytes'] for x in provenance['files']) / 1024**3, 3), flush=True)

if __name__ == '__main__':
    main()
