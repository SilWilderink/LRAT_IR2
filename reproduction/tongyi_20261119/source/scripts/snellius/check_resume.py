"""Regression check for the raw-encoder checkpoint format; run via Slurm."""
import os
import tempfile
import unittest
from pathlib import Path

import torch
from transformers import Qwen3Config, Qwen3Model, TrainingArguments
from FlagEmbedding.finetune.embedder.decoder_only.base.trainer import DecoderOnlyEmbedderTrainer


class Retriever(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = Qwen3Model(Qwen3Config(
            vocab_size=16, hidden_size=8, intermediate_size=16,
            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
            head_dim=4,
        ))

    def save(self, output_dir):
        self.model.save_pretrained(output_dir)


class ResumeCheckpointTest(unittest.TestCase):
    def test_raw_encoder_weights_are_restored_into_inner_model(self):
        with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as directory:
            model = Retriever()
            args = TrainingArguments(
                output_dir=str(Path(directory) / "output"), use_cpu=True,
                report_to="none", save_safetensors=True,
            )
            trainer = DecoderOnlyEmbedderTrainer(model=model, args=args)
            with torch.no_grad():
                for parameter in model.parameters():
                    parameter.fill_(0.25)
            checkpoint = str(Path(directory) / "checkpoint")
            trainer._save(checkpoint)
            for explicit_model in (False, True):
                with self.subTest(explicit_model=explicit_model):
                    with torch.no_grad():
                        for parameter in model.parameters():
                            parameter.zero_()
                    if explicit_model:
                        trainer._load_from_checkpoint(checkpoint, model=model)
                    else:
                        trainer._load_from_checkpoint(checkpoint)
                    for parameter in model.parameters():
                        torch.testing.assert_close(parameter, torch.full_like(parameter, 0.25))


if __name__ == "__main__":
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Submit check_resume.sbatch for this test.")
    unittest.main()
