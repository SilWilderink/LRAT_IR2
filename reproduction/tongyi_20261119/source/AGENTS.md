# Working on LRAT on Snellius

- This checkout is used on SURF's Snellius cluster through a UvA account.
- Run experiments, training, inference, indexing, and GPU validation through
  Slurm (`sbatch`, or `srun` inside an allocation). Do not run those workloads
  on login nodes. Lightweight inspection and software setup are permitted.
- Keep source and small configuration in the home checkout. Keep canonical
  datasets in permanent storage, configured by `LRAT_DATA_ROOT` (default:
  `/home/$USER/datasets/lrat`). Prepared training copies, subsets, model
  downloads, environments, caches, indexes, and intermediate run artifacts
  belong on scratch. Stage training inputs into the job-provided `$TMPDIR`;
  do not use system `/tmp` for job files.
- Shared scratch is temporary and unbacked; preserve important outputs in
  durable project storage or another suitable destination.
- The fine-tuning environment is `environments/snellius/pyproject.toml` with
  its own `uv.lock`. Source `scripts/snellius/env.sh` before using it.
  The upstream root lock lacks a matching manifest; do not assume root
  `uv sync` works, or overwrite that lock when preparing this environment.
- See `docs/snellius.md` and `scripts/snellius/` for the setup and Slurm jobs.
  Machine-specific account/path settings belong in ignored
  `scripts/snellius/local.sh`.
