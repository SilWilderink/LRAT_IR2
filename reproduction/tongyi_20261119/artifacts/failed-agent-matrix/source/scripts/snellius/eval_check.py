"""Offline regression checks for evaluation protocol, using fake model responses."""
import ast
import json
import re
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

repo = Path(__file__).resolve().parents[2]
module = ast.parse((repo / "scripts/snellius/eval_agent.py").read_text())
namespace = {
    "ast": ast, "Path": Path, "re": re, "time": time, "json5": json,
    "Counter": Counter, "SEED": 2025, "MAX_CALLS": 50, "PROTOCOL": {},
}
for node in module.body:
    if isinstance(node, ast.FunctionDef) and node.name in ("run_agent", "parse_judge", "load_prompt"):
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(repo / "scripts/snellius/eval_agent.py"), "exec"), namespace)


class Retriever:
    def search(self, query):
        return "DocID:1\nExample", ["1"]
    def document(self, docid):
        return "Example document", ["1"]


class Tokenizer:
    def apply_chat_template(self, *args, **kwargs):
        return [1, 2, 3]


def fake_api(responses, requests):
    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            requests.append(kwargs)
            content = responses[min(len(requests)-1, len(responses)-1)]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
                usage=SimpleNamespace(completion_tokens=10),
            )
        def close(self):
            pass
    return Client


class ProtocolTest(unittest.TestCase):
    def test_search_browse_answer(self):
        requests = []
        namespace["OpenAI"] = fake_api([
            '<tool_call>{"name":"search","arguments":{"query":"test"}}</tool_call>',
            '<tool_call>{"name":"get_document","arguments":{"docid":"1"}}</tool_call>',
            "<answer>result</answer>",
        ], requests)
        record = namespace["run_agent"]("1", "test question", Retriever(), Tokenizer(), "system", "localhost")
        self.assertEqual(record["prediction"], "result")
        self.assertEqual(record["model_calls"], 3)
        self.assertEqual(record["retrieved_docids"], ["1"])
        self.assertEqual(record["tool_call_counts"], {"search": 1, "get_document": 1})
        self.assertEqual(requests[0]["temperature"], 0.85)
        self.assertEqual(requests[0]["seed"], 2025)

    def test_empty_model_completion_is_a_no_answer_outcome(self):
        requests = []
        namespace["OpenAI"] = fake_api([""], requests)
        record = namespace["run_agent"]("1", "question", Retriever(), Tokenizer(), "system", "localhost")
        self.assertEqual(record["status"], "empty_response")
        self.assertEqual(record["prediction"], "")
        self.assertEqual(record["model_calls"], 1)

    def test_fifty_model_call_cap(self):
        requests = []
        namespace["OpenAI"] = fake_api(
            ['<tool_call>{"name":"search","arguments":{"query":"test"}}</tool_call>'], requests)
        record = namespace["run_agent"]("1", "question", Retriever(), Tokenizer(), "system", "localhost")
        self.assertEqual(len(requests), 50)
        self.assertEqual(record["model_calls"], 50)
        self.assertIn("Final step", requests[-1]["messages"][-2]["content"])
        self.assertEqual(sum(record["tool_call_counts"].values()), 49)

    def test_parse_judge_requires_explicit_decision(self):
        self.assertTrue(namespace["parse_judge"]("reasoning: text\ncorrect: yes"))
        self.assertFalse(namespace["parse_judge"]("correct: no"))
        self.assertIsNone(namespace["parse_judge"]("There is no decision yet."))

    def test_load_existing_prompt_constants(self):
        for relative, name in [
            ("search_agent/tongyi_utils/react_agent.py", "SYSTEM_PROMPT_SEARCH_ONLY"),
            ("scripts_evaluation/evaluate.py", "JUDGE_TEMPLATE"),
        ]:
            self.assertTrue(namespace["load_prompt"](repo, relative, name))


if __name__ == "__main__":
    unittest.main()
