"""CPU checks for InfoSeek scoring and exact shard/document-ID assembly; use Slurm."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import faiss
import numpy as np
from eval_agent import load_questions, aggregate_metrics
from infoseek_index import partition, fingerprint, merge


class InfoSeekTest(unittest.TestCase):
    def test_actual_question_file_has_300_unique_triples(self):
        repo=Path(__file__).resolve().parents[2]
        rows=load_questions(repo/'datasets','InfoSeek-Eval.tsv')
        self.assertEqual(len(rows),300)
        self.assertEqual(len({row[0] for row in rows}),300)
        self.assertTrue(all(len(row)==3 and all(row) for row in rows))

    def test_infoseek_scores_do_not_invent_evidence_recall(self):
        rows=[{'correct':True,'steps':2,'model_calls':3},
              {'correct':False,'steps':4,'model_calls':5}]
        metrics=aggregate_metrics(rows,False)
        self.assertEqual(metrics,{'Success Rate':0.5,'Avg Steps':3,'Avg Model Calls':4})

    def test_browsecomp_scoring_still_averages_evidence_fractions(self):
        rows=[{'correct':True,'steps':2,'model_calls':3,'evidence_recall':0.25,'any_evidence':True},
              {'correct':False,'steps':4,'model_calls':5,'evidence_recall':0.,'any_evidence':False}]
        metrics=aggregate_metrics(rows,True)
        self.assertEqual(metrics['Evidence Recall'],0.125)
        self.assertEqual(metrics['Any Evidence Hit Rate'],0.5)

    def test_uneven_shards_preserve_all_vectors_and_nonsequential_ids(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as directory:
            root=Path(directory)
            model=root/'model';model.mkdir()
            (model/'config.json').write_text(json.dumps({'hidden_size':2}))
            ids=np.asarray([42,7,1001,2,5,99,11],dtype='<i8')
            ids.tofile(root/'source.i64')
            assets={'trained_model':str(model),'model_sha256':'test-model','corpus_sha256':'test-corpus',
                    'corpus_count':7,'corpus_docids':str(root/'source.i64'),'revisions':{'corpus':['test','pinned']}}
            out=root/'index';out.mkdir()
            angles=np.arange(7)*2*np.pi/7
            vectors=np.stack([np.cos(angles),np.sin(angles)],axis=1).astype('float32')
            covered=[]
            for rank in range(4):
                start,stop=partition(7,rank,4)
                covered.extend(range(start,stop))
                shard=out/'shards'/str(rank);shard.mkdir(parents=True)
                np.save(shard/'vectors.npy',vectors[start:stop])
                (shard/'progress.json').write_text(json.dumps({'fingerprint':fingerprint(assets,4),'encoded':stop-start}))
            self.assertEqual(covered,list(range(7)))
            merge(assets,out,4)
            index=faiss.read_index(str(out/'index.faiss'))
            scores,positions=index.search(vectors,1)
            mapping=np.memmap(out/'docids.i64',dtype='<i8',mode='r')
            np.testing.assert_array_equal(mapping[positions[:,0]],ids)
            np.testing.assert_allclose(scores[:,0],1,atol=1e-6)
            manifest=json.loads((out/'manifest.json').read_text())
            self.assertEqual(manifest['documents'],7)


if __name__=='__main__':
    if not os.environ.get('SLURM_JOB_ID'):raise SystemExit('Use infoseek_prepare.sbatch')
    unittest.main()
