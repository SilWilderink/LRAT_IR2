"""Small CPU regression tests, executed by the E5 Slurm setup job."""
import os
import tempfile
import unittest
from pathlib import Path

import torch
from transformers import XLMRobertaConfig, XLMRobertaModel, TrainingArguments
from FlagEmbedding.finetune.embedder.encoder_only.base.modeling import BiEncoderOnlyEmbedderModel
from FlagEmbedding.finetune.embedder.encoder_only.base.trainer import EncoderOnlyEmbedderTrainer
from eval_embedding import pool_embeddings, E5_RETRIEVAL, retrieval_settings


class RepresentationModel(BiEncoderOnlyEmbedderModel):
    def encode(self, features):
        return features


class E5Test(unittest.TestCase):
    def test_forward_uses_example_weights_and_weighted_gradients(self):
        model = RepresentationModel(torch.nn.Linear(2, 2), temperature=0.5)
        queries = torch.tensor([[1., 0.], [0., 1.]], requires_grad=True)
        passages = torch.tensor([[1., 0.], [0.7, 0.3], [0.2, 0.8], [0., 1.]])
        scores = queries @ passages.T / 0.5
        per_sample = torch.nn.functional.cross_entropy(scores, torch.tensor([0, 2]), reduction="none")
        expected = (per_sample * torch.tensor([1., 9.])).sum() / 10
        actual = model(queries=queries, passages=passages, reweight_rates=[1., 9.]).loss
        torch.testing.assert_close(actual, expected)
        self.assertGreater(abs(actual.item() - per_sample.mean().item()), 0.01)
        actual_grad, = torch.autograd.grad(actual, queries, retain_graph=True)
        expected_grad, = torch.autograd.grad(expected, queries)
        torch.testing.assert_close(actual_grad, expected_grad)
        unweighted = model(queries=queries, passages=passages).loss
        torch.testing.assert_close(unweighted, per_sample.mean())

    def test_padding_is_excluded_from_mean_and_last_token(self):
        hidden = torch.tensor([[[1., 3.], [3., 5.], [100., 100.]],
                               [[100., 100.], [5., 7.], [7., 9.]]])
        mask = torch.tensor([[1, 1, 0], [0, 1, 1]])
        torch.testing.assert_close(pool_embeddings(hidden, mask, "mean"), torch.tensor([[2., 4.], [6., 8.]]))
        torch.testing.assert_close(pool_embeddings(hidden, mask, "last_token"), torch.tensor([[3., 5.], [7., 9.]]))
        self.assertEqual(retrieval_settings({})["pooling"], "last_token")
        self.assertEqual(retrieval_settings({"retrieval":E5_RETRIEVAL})["pooling"], "mean")
        self.assertTrue(E5_RETRIEVAL["query_prefix"].endswith("Query: "))
        self.assertEqual(E5_RETRIEVAL["passage_prefix"], "")

    def test_ddp_runs_two_steps_with_unused_pooler_and_checkpointing(self):
        # Reproduce the full launcher's DDP path: the pooler is unused when
        # loss consumes mean-pooled last_hidden_state. Step two must succeed.
        import torch.distributed as dist
        from torch.nn.parallel import DistributedDataParallel
        with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as directory:
            dist.init_process_group("gloo", init_method="file://" + str(Path(directory)/"group"),
                                    rank=0, world_size=1)
            try:
                encoder = XLMRobertaModel(XLMRobertaConfig(
                    vocab_size=32, hidden_size=8, intermediate_size=16,
                    num_hidden_layers=1, num_attention_heads=2, max_position_embeddings=32,
                    hidden_dropout_prob=0.0, attention_probs_dropout_prob=0.0))
                model = BiEncoderOnlyEmbedderModel(encoder, sentence_pooling_method="mean",
                                                   normalize_embeddings=True, temperature=0.02)
                model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
                model.enable_input_require_grads()
                wrapped = DistributedDataParallel(model, find_unused_parameters=True)
                optimizer = torch.optim.SGD(model.parameters(), lr=1e-4)
                queries = {"input_ids":torch.tensor([[0,5,6,2],[0,7,8,2]]),
                           "attention_mask":torch.ones(2,4,dtype=torch.long)}
                passages = [queries, {"input_ids":torch.tensor([[0,9,10,2],[0,11,12,2]]),
                                      "attention_mask":torch.ones(2,4,dtype=torch.long)}]
                for _ in range(2):
                    optimizer.zero_grad(set_to_none=True)
                    loss = wrapped(queries=queries, passages=passages, reweight_rates=[1., 2.]).loss
                    self.assertTrue(torch.isfinite(loss))
                    loss.backward()
                    self.assertIsNone(encoder.pooler.dense.weight.grad)
                    self.assertIsNotNone(encoder.encoder.layer[0].attention.self.query.weight.grad)
                    optimizer.step()
            finally:
                dist.destroy_process_group()

    def test_checkpoint_restores_encoder_weights(self):
        with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as directory:
            encoder = XLMRobertaModel(XLMRobertaConfig(
                vocab_size=32, hidden_size=8, intermediate_size=16,
                num_hidden_layers=1, num_attention_heads=2, max_position_embeddings=32))
            model = BiEncoderOnlyEmbedderModel(encoder, sentence_pooling_method="mean")
            args = TrainingArguments(output_dir=str(Path(directory)/"output"), use_cpu=True, report_to="none")
            trainer = EncoderOnlyEmbedderTrainer(model=model, args=args)
            with torch.no_grad():
                for parameter in model.parameters():
                    parameter.fill_(0.25)
            checkpoint = str(Path(directory)/"checkpoint")
            trainer._save(checkpoint)
            for explicit in (False, True):
                with torch.no_grad():
                    for parameter in model.parameters():
                        parameter.zero_()
                trainer._load_from_checkpoint(checkpoint, model=model if explicit else None)
                for parameter in model.parameters():
                    torch.testing.assert_close(parameter, torch.full_like(parameter, 0.25))


if __name__ == "__main__":
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Run via e5_setup.sbatch")
    unittest.main()
