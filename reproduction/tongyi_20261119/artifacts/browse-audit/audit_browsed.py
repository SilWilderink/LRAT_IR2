"""Audit successful BrowseComp document opens against positive evidence/gold qrels.

The primary unit is a unique (question, document) pair within a retriever run.
Repeated successful opens are counted separately as a secondary metric.
"""
import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
import json5


def qrels(path):
    result = defaultdict(set)
    for line in path.read_text().splitlines():
        qid, _, docid, label = line.split()
        if float(label) > 0:
            result[qid].add(docid)
    return result


def browse_events(record):
    messages = record['raw_messages']
    last_search = None
    for i, message in enumerate(messages):
        if message['role'] != 'assistant':
            continue
        # Historical runner executes only the first tool call in each response.
        match = re.search(r'<tool_call>(.*?)</tool_call>', message['content'], re.S)
        if not match or i+1 >= len(messages):
            continue
        try:
            action = json5.loads(match.group(1))
            name, arguments = action.get('name'), action.get('arguments', {})
        except (ValueError, AttributeError):
            continue
        if name == 'search':
            last_search = arguments.get('query')
            continue
        if name not in ('get_document', 'visit'):
            continue
        response = messages[i+1]
        if response['role'] != 'user':
            continue
        opened = re.match(r'<tool_response>\s*Document ([^:\n]+):\n', response['content'])
        if not opened:
            continue  # excludes missing-document/error/invalid-call outputs
        docid = opened.group(1)
        requested = arguments.get('docid')
        if isinstance(requested,list):
            requested = requested[0] if requested else None
        if str(requested) != docid:
            raise RuntimeError('Requested/returned document mismatch')
        after = next((m['content'] for m in messages[i+2:] if m['role']=='assistant'), '')
        yield {'docid':docid,'message_index':i,'last_search_query':last_search,
               'pre_browse_response':message['content'],
               'document_view':response['content'], 'post_browse_response':after}


def self_check():
    def call(doc):
        return {'role':'assistant','content':'<tool_call>{"name":"get_document","arguments":{"docid":"'+doc+'"}}</tool_call>'}
    record={'raw_messages':[call('7'),{'role':'user','content':'<tool_response>\nDocument 7:\ntext\n</tool_response>'},
                            call('7'),{'role':'user','content':'<tool_response>\nDocument 7:\ntext\n</tool_response>'},
                            call('8'),{'role':'user','content':'<tool_response>\n[Document not found] docid=8\n</tool_response>'}]}
    events=list(browse_events(record))
    assert len(events)==2 and {e['docid'] for e in events}=={'7'}
    assert events[0]['post_browse_response']==record['raw_messages'][2]['content']


def summarize(events, pairs, query_counts):
    def counts(rows):
        return {'total':len(rows),
                'not_evidence':sum(not r['evidence_labeled'] for r in rows),
                'not_gold':sum(not r['gold_labeled'] for r in rows),
                'not_evidence_percent':100*sum(not r['evidence_labeled'] for r in rows)/len(rows) if rows else None,
                'not_gold_percent':100*sum(not r['gold_labeled'] for r in rows)/len(rows) if rows else None}
    return {'successful_browse_events':counts(events),'unique_question_document_pairs':counts(pairs),
            'questions_with_browsing':sum(bool(n) for n in query_counts),
            'questions_without_browsing':sum(not n for n in query_counts),
            'correct_task_pairs':counts([r for r in pairs if r['task_correct']]),
            'incorrect_task_pairs':counts([r for r in pairs if not r['task_correct']])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    args=parser.parse_args()
    if not os.environ.get('SLURM_JOB_ID'):
        raise SystemExit('Run through Slurm')
    self_check()
    args.output.mkdir(parents=True,exist_ok=True)
    base=Path(os.environ['LRAT_SCRATCH_ROOT'])/'evaluation'
    sources={'qwen':base/'tongyi-trained-28880868','e5':base/'e5-large-tongyi-20261104T204422Z'}
    summary={'job_id':os.environ['SLURM_JOB_ID'],
             'definition':'Successful document opens only. Primary: unique question/document pairs per retriever. Positive qrel_evidence labels. Absence does not imply irrelevance.',
             'models':{},'sources':{},'qrels_sha256':{}}
    samples=[]
    review_fields=['retriever','query_id','docid','visits','task_correct','gold_labeled','question','first_event_id','annotation_usefulness','annotation_notes']
    with (args.output/'review_pairs.csv').open('w',newline='') as review, gzip.open(args.output/'browse_events.jsonl.gz','wt') as output:
        writer=csv.DictWriter(review,fieldnames=review_fields)
        writer.writeheader()
        for retriever,root in sources.items():
            assets=json.loads((root/'assets.json').read_text())
            protocol=Path(assets['protocol_path'])
            evidence,gold=qrels(protocol/'qrel_evidence.txt'),qrels(protocol/'qrel_golds.txt')
            for name in ['qrel_evidence.txt','qrel_golds.txt']:
                summary['qrels_sha256'][name]=hashlib.sha256((protocol/name).read_bytes()).hexdigest()
            rows=list(csv.reader((protocol/'browsecomp-plus.tsv').open(),delimiter='\t',quoting=csv.QUOTE_NONE))
            questions={r[0].strip():r[1].strip() for r in rows}
            results=json.loads((root/'full-results.json').read_text())
            details={d['query_id']:d for d in results['details']}
            if len(details)!=830 or set(details)!=set(questions):
                raise RuntimeError('Expected all 830 scored questions')
            if any(not evidence[qid] for qid in questions):
                raise RuntimeError('Question without positive evidence labels')
            all_events,all_pairs,query_counts=[],[],[]
            sample_groups=defaultdict(list)
            for qid in sorted(questions):
                path=root/'trajectories'/(qid+'.json')
                record=json.loads(path.read_text())
                if record['query_id']!=qid or record.get('status')=='infrastructure_error':
                    raise RuntimeError('Invalid trajectory: '+str(path))
                events=list(browse_events(record))
                expected=sum(record.get('tool_call_counts',{}).get(k,0) for k in ('get_document','visit'))
                if len(events)!=expected:
                    raise RuntimeError(f'Browse counter mismatch {path}: parsed {len(events)}, recorded {expected}')
                query_counts.append(len(events))
                visits=Counter(e['docid'] for e in events)
                seen=set()
                for e in events:
                    e.update(retriever=retriever,query_id=qid,question=questions[qid],task_correct=bool(details[qid]['correct']),
                             evidence_labeled=e['docid'] in evidence[qid],gold_labeled=e['docid'] in gold[qid],
                             event_id=f"{retriever}:{qid}:{e['message_index']}",trajectory=str(path))
                    output.write(json.dumps(e,ensure_ascii=False)+'\n')
                    flags={k:e[k] for k in ('evidence_labeled','gold_labeled','task_correct')}
                    all_events.append(flags)
                    if e['docid'] not in seen:
                        all_pairs.append(flags);seen.add(e['docid'])
                        if not e['evidence_labeled']:
                            writer.writerow({**{k:e[k] for k in ['retriever','query_id','docid','task_correct','gold_labeled','question']},
                                             'visits':visits[e['docid']],'first_event_id':e['event_id'],
                                             'annotation_usefulness':'','annotation_notes':''})
                            sample_groups[e['task_correct']].append(e)
            summary['models'][retriever]=summarize(all_events,all_pairs,query_counts)
            summary['sources'][retriever]=str(root)
            for correct,group in sample_groups.items():
                samples.extend(random.Random(2025).sample(group,min(5,len(group))))
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (args.output/'review_sample.json').write_text(json.dumps(samples,ensure_ascii=False,indent=2)+'\n')
    text=['# Browsed documents absent from evidence labels','',
          'Deterministic sample: up to five pairs from correct and incorrect tasks per retriever. Labels record benchmark membership, not usefulness to the agent. Full text and context are in review_sample.json; all browse events are in browse_events.jsonl.gz.','']
    for e in samples:
        text += [f"## {e['event_id']} — document {e['docid']}",'',f"Task correct: {e['task_correct']}. Question: {e['question']}",'',
                 '**Document shown to agent**','',e['document_view'][:3000],'','**Next agent response (excerpt)**','',
                 e['post_browse_response'][:3500],'','Usefulness annotation: ____; supporting reasoning: ____','']
    (args.output/'review_sample.md').write_text('\n'.join(text))
    args.archive.mkdir(parents=True,exist_ok=True)
    for source in sorted(args.output.iterdir()):
        if source.is_file():
            target=args.archive/source.name
            shutil.copy2(source,target)
            if hashlib.sha256(source.read_bytes()).digest()!=hashlib.sha256(target.read_bytes()).digest():
                raise RuntimeError('Archive mismatch')
    shutil.copy2(__file__,args.archive/'audit_browsed.py')
    (args.archive/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
                                               for p in sorted(args.archive.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
    print(json.dumps(summary,indent=2),flush=True)
    print('Archived:',args.archive,flush=True)


if __name__=='__main__':
    main()
