"""Fail early if a Slurm job cannot use its assigned GPU."""
import json
import os

import torch
import FlagEmbedding

if not os.environ.get("SLURM_JOB_ID"):
    raise SystemExit("Run this check inside a Slurm GPU job.")
if not torch.cuda.is_available():
    raise SystemExit("CUDA is unavailable inside the GPU allocation.")
value = torch.ones(32, device="cuda")
assert value.sum().item() == 32
print(json.dumps({
    "torch": torch.__version__,
    "cuda_runtime": torch.version.cuda,
    "gpu_count": torch.cuda.device_count(),
    "gpu_name": torch.cuda.get_device_name(0),
    "flagembedding": FlagEmbedding.__file__,
}, indent=2))
