"""CPU-only regression checks for model-specific answer termination."""
import types
import unittest
from unittest.mock import patch
import eval_agent as agent


class Tokenizer:
    def apply_chat_template(self, *args, **kwargs):
        return [1, 2, 3]


class Retriever:
    def search(self, query):
        return "a document", ["17"]


class ProtocolChecks(unittest.TestCase):
    def run_case(self, responses, mode):
        calls = iter(responses)
        def create(**kwargs):
            content, finish = next(calls)
            return types.SimpleNamespace(usage=None, choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content=content), finish_reason=finish)])
        client = types.SimpleNamespace(chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=create)), close=lambda: None)
        with patch.object(agent, "OpenAI", return_value=client), patch.dict(agent.PROTOCOL, {"answer_mode": mode}):
            return agent.run_agent("q", "question", Retriever(), Tokenizer(), "system", "http://unused")

    def test_plain_answer_after_search(self):
        result = self.run_case([
            ('<tool_call>{"name":"search","arguments":{"query":"x"}}</tool_call>', "stop"),
            ("The answer is Oslo.", "stop"),
        ], "plain_or_tagged")
        self.assertEqual(result["prediction"], "The answer is Oslo.")
        self.assertEqual(result["tool_call_counts"], {"search": 1})
        self.assertEqual(result["model_calls"], 2)

    def test_truncated_thought_is_not_answer(self):
        result = self.run_case([("still reasoning", "length"), ("Oslo", "stop")], "plain_or_tagged")
        self.assertEqual(result["prediction"], "Oslo")
        self.assertEqual(result["model_calls"], 2)

    def test_tongyi_keeps_tag_requirement(self):
        result = self.run_case([("thinking", "stop"), ("<answer>Oslo</answer>", "stop")], "tagged")
        self.assertEqual(result["prediction"], "Oslo")
        self.assertEqual(result["model_calls"], 2)


if __name__ == "__main__":
    unittest.main()
