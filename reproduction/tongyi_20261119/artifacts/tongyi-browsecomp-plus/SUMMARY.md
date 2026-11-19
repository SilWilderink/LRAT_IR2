# Completed LRAT experiments

Agent: Tongyi-DeepResearch-30B-A3B. Benchmark: BrowseComp-Plus, 830 questions each.

| Retriever | Correct | Success rate | Evidence recall | Avg. tool steps | Avg. model calls | Any evidence hit | Train batch/group |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen3-Embedding-0.6B + LRAT | 173/830 | 20.84% | 46.91% | 44.50 | 47.17 | 78.80% | 2/2 |
| Multilingual-E5-Large-Instruct + LRAT | 218/830 | 26.27% | 56.89% | 43.19 | 46.52 | 86.51% | 32/10 |

Both retrievers completed two epochs on 96,503 prepared LRAT-Train examples.
Training configurations differ, so these runs are not a controlled backbone comparison.
Base-retriever baselines remain deferred; no baseline improvement is established.

Each experiment contains a standalone model/ directory (weights, config, tokenizer),
evaluation/full-results.json, and provenance/. Per-question trajectories and judgments
are preserved as evaluation/trajectories.tar.gz and evaluation/judgments.tar.gz.
The executed evaluation-code snapshots are in evaluation/source.tar.gz.

Load the archived model with Transformers AutoModel/AutoTokenizer and use retrieval.json
for pooling, padding, normalization, input lengths and the query instruction.
Qwen uses normalized last-token pooling; E5 uses normalized masked mean pooling.
Original scratch paths in reports/provenance are retained unchanged as execution history.
The model_path/results_path fields in summary.json point to the permanent copies.

Training optimizer checkpoints, indexes, corpus working copies, environments and agent/judge
model downloads are outside this archive. Canonical datasets remain in permanent storage.

SHA256SUMS and archive-manifest.json record the preserved file checksums.
