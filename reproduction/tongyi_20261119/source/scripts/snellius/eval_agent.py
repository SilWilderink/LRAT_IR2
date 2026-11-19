"""Resumable agent evaluation of trained LRAT retrievers on both benchmarks."""
import argparse
import ast
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import statistics
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import faiss
import json5
import numpy as np
import torch
from openai import OpenAI
from transformers import AutoModel, AutoTokenizer
from eval_embedding import retrieval_settings, pool_embeddings

SEED = 2025
MAX_CALLS = 50
QUERY_PREFIX = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
PROTOCOL = {
    "benchmark": "BrowseComp-Plus", "agent": "Tongyi-DeepResearch-30B-A3B",
    "temperature": 0.85, "top_p": 0.95, "presence_penalty": 1.1, "seed": SEED,
    "max_model_calls": MAX_CALLS, "top_k": 10, "snippet_tokens": 64,
    "document_tokens": 512, "query_max_length": 512,
    "generation_caps": [4096, 2048, 1024], "final_generation_cap": 10000,
    "context_soft_limit": 100000,
}
STATS_NAMES = ("Success Rate", "Avg Steps", "Evidence Recall")


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def load_questions(protocol, filename="browsecomp-plus.tsv"):
    with (Path(protocol) / filename).open(newline="") as file:
        rows = list(csv.reader(file, delimiter="\t", quoting=csv.QUOTE_NONE))
    return [(row[0].strip(), row[1].strip(), row[2].strip()) for row in rows]


def load_prompt(repo, relative, constant):
    # Read the existing prompt verbatim without importing optional agent frameworks.
    module = ast.parse((Path(repo) / relative).read_text())
    for node in module.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets):
            value = node.value
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "strip" and not value.args and not value.keywords):
                return ast.literal_eval(value.func.value).strip()
            return ast.literal_eval(value)
    raise RuntimeError("Prompt constant missing: " + constant)


def pilot_questions(rows, count):
    indexes = sorted(random.Random(SEED).sample(range(len(rows)), min(count, len(rows))))
    return [rows[index] for index in indexes]


def complete_file(path):
    if not path.exists():
        return False
    try:
        record = json.loads(path.read_text())
        return record.get("status") != "infrastructure_error" and bool(record.get("query_id"))
    except (ValueError, OSError):
        return False


class LockedTokenizer:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.lock = threading.Lock()

    def apply_chat_template(self, *args, **kwargs):
        with self.lock:
            return self.tokenizer.apply_chat_template(*args, **kwargs)


class Retriever:
    def __init__(self, assets, index_root):
        self.settings = retrieval_settings(assets)
        self.index = faiss.read_index(str(index_root / "index.faiss"))
        if (index_root / "docids.i64").is_file():
            self.ids = np.memmap(index_root / "docids.i64", dtype="<i8", mode="r")
        else:
            self.ids = json.loads((index_root / "docids.json").read_text())
        if len(self.ids) != self.index.ntotal:
            raise RuntimeError("Index and document ID counts differ")
        self.tokenizer = AutoTokenizer.from_pretrained(
            assets["trained_model"], padding_side=self.settings["padding_side"], local_files_only=True)
        self.model = AutoModel.from_pretrained(
            assets["trained_model"], torch_dtype=torch.bfloat16,
            attn_implementation="sdpa", local_files_only=True).to("cuda:0").eval()
        self.database = assets["corpus_database"]
        self.local = threading.local()
        self.lock = threading.Lock()
        faiss.omp_set_num_threads(4)
        torch.set_num_threads(4)

    def connection(self):
        if not hasattr(self.local, "connection"):
            self.local.connection = sqlite3.connect("file:" + self.database + "?mode=ro", uri=True)
        return self.local.connection

    def text(self, docid):
        row = self.connection().execute("SELECT text FROM documents WHERE docid=?", (str(docid),)).fetchone()
        return row[0] if row else None

    def truncate(self, text, count):
        with self.lock:
            tokens = self.tokenizer.encode(text, add_special_tokens=False, truncation=True, max_length=count)
            return self.tokenizer.decode(tokens, skip_special_tokens=True)

    def search(self, query):
        if isinstance(query, list):
            query = query[0]
        if not isinstance(query, str) or not query.strip():
            return "Invalid search query.", []
        with self.lock:
            inputs = self.tokenizer(
                [self.settings["query_prefix"] + query], max_length=self.settings["max_length"], truncation=True,
                padding=True, return_tensors="pt").to("cuda:0")
            with torch.inference_mode():
                hidden = self.model(**inputs).last_hidden_state
                representation = pool_embeddings(hidden, inputs["attention_mask"], self.settings["pooling"])
                if self.settings["normalize"]:
                    representation = torch.nn.functional.normalize(representation, dim=-1)
                representation = representation.cpu().numpy()
            _, positions = self.index.search(np.ascontiguousarray(representation), 10)
        docids = [str(self.ids[int(index)]) for index in positions[0] if index >= 0]
        results = []
        for docid in docids:
            text = self.text(docid)
            title = ""
            if text.startswith("---\ntitle:"):
                title = text.split("\n")[1].replace("title:", "").strip().strip('"')
            if not title:
                first = text.split("\n", 1)[0].strip()
                title = first[:50] + "..." if len(first) > 50 else first
            results.append(f"DocID:{docid}\n[{title}]\n{self.truncate(text, 64)}")
        return f"A search for '{query}' found {len(results)} results:\n\n## Web Results\n" + "\n\n".join(results), docids

    def document(self, docid):
        if isinstance(docid, list):
            docid = docid[0]
        text = self.text(str(docid))
        if text is None:
            return f"[Document not found] docid={docid}", []
        return f"Document {docid}:\n{self.truncate(text, 512)}.", [str(docid)]


def run_agent(qid, question, retriever, agent_tokenizer, system_prompt, base_url):
    started = time.monotonic()
    client = OpenAI(base_url=base_url, api_key="EMPTY", timeout=600, max_retries=2)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": question}]
    counts, attempted = Counter(), Counter()
    retrieved, events, tool_events = set(), [], []
    final = ""
    status = "max_model_calls"
    thinking = True
    total_tokens = 0
    for turn in range(1, MAX_CALLS + 1):
        tokens = len(agent_tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True))
        forced = turn == MAX_CALLS or tokens > 100000
        if forced:
            messages.append({"role": "user", "content":
                "Final step reached. You must not call tools. Give your best final answer"
                + ("." if PROTOCOL.get("answer_mode") == "plain_or_tagged" else " inside <answer></answer>.")})
        cap = 10000 if forced else (4096 if turn == 1 else 2048 if turn == 2 else 1024)
        call_started = time.monotonic()
        response = client.chat.completions.create(
            model="lrat-eval-agent", messages=messages, temperature=0.85,
            top_p=0.95, presence_penalty=1.1, seed=SEED, max_tokens=cap,
            stop=["\n<tool_response>", "<tool_response>"],
            extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        )
        content = response.choices[0].message.content or ""
        finish = response.choices[0].finish_reason
        if response.usage:
            total_tokens += response.usage.completion_tokens
        events.append({"turn": turn, "seconds": time.monotonic() - call_started,
                       "finish_reason": finish, "prompt_tokens": tokens, "max_tokens": cap})
        if not content.strip():
            status = "empty_response"
            break
        messages.append({"role": "assistant", "content": content})
        thinking = True
        answer = re.search(r"<answer>(.*?)</answer>", content, re.S)
        if answer:
            final, status = answer.group(1).strip(), "answer"
            break
        if forced:
            final = content.strip()
            status = "final_without_answer_tags"
            break
        tool = re.search(r"<tool_call>(.*?)</tool_call>", content, re.S)
        if tool:
            name, arguments, ids = "", {}, []
            try:
                action = json5.loads(tool.group(1))
                name = action.get("name", "")
                arguments = action.get("arguments", {})
                attempted[name] += 1
                if name == "search":
                    output, ids = retriever.search(arguments["query"])
                elif name in ("get_document", "visit"):
                    output, ids = retriever.document(arguments["docid"])
                else:
                    output, ids = f"Error: Tool {name} does not exist.", []
                if ids:
                    counts[name] += 1
                    retrieved.update(ids)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                attempted["invalid_tool_call"] += 1
                output = "Invalid tool call. Use search with a query string or get_document with a docid string."
            tool_events.append({"turn": turn, "name": name, "arguments": arguments,
                                "returned_docids": ids, "successful": bool(ids)})
            messages.append({"role": "user", "content": "<tool_response>\n" + output + "\n</tool_response>"})
        elif finish == "length":
            messages.append({"role": "user", "content":
                "<tool_response>\nYour previous thought was truncated. Directly provide a tool call or final answer.\n</tool_response>"})
            thinking = False
        elif PROTOCOL.get("answer_mode") == "plain_or_tagged":
            # The repository WebExplorer/AgentCPM clients accept a completed
            # non-tool response as the final answer; their prompt requires no tags.
            final, status = content.strip(), "answer"
            break
    client.close()
    return {
        "query_id": qid, "status": status, "prediction": final,
        "result": [{"type": "output_text", "output": final}],
        "tool_call_counts": dict(counts), "tool_call_counts_all": dict(attempted),
        "retrieved_docids": sorted(retrieved), "raw_messages": messages,
        "tool_events": tool_events,
        "model_calls": len(events), "events": events, "completion_tokens": total_tokens,
        "elapsed_seconds": time.monotonic() - started, "protocol": PROTOCOL,
    }



def aggregate_metrics(details, has_qrels):
    metrics = {
        "Success Rate": statistics.mean(x["correct"] for x in details),
        "Avg Steps": statistics.mean(x["steps"] for x in details),
        "Avg Model Calls": statistics.mean(x["model_calls"] for x in details),
    }
    if has_qrels:
        metrics.update({
            "Evidence Recall": statistics.mean(x["evidence_recall"] for x in details),
            "Any Evidence Hit Rate": statistics.mean(x["any_evidence"] for x in details),
        })
    return metrics


def parse_judge(content):
    matches = re.findall(r"^\s*correct\s*:\s*['\"]?(yes|no)\b", content, re.I | re.M)
    return None if not matches else matches[-1].lower() == "yes"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["agent", "judge"])
    parser.add_argument("mode", choices=["pilot", "full"])
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise SystemExit("Use Slurm for model evaluation.")
    root = Path(os.environ["LRAT_EVAL_ROOT"])
    assets = json.loads(Path(os.environ["LRAT_EVAL_ASSETS"]).read_text())
    PROTOCOL["retriever"] = {"model_path": assets["trained_model"], **retrieval_settings(assets)}
    benchmark = assets.get("benchmark", "BrowseComp-Plus")
    PROTOCOL["benchmark"] = benchmark
    PROTOCOL["agent"] = assets.get("agent_name", "Tongyi-DeepResearch-30B-A3B")
    PROTOCOL["answer_mode"] = assets.get("answer_mode", "tagged")
    prompt_source = assets.get("agent_prompt", "search_agent/tongyi_utils/react_agent.py")
    PROTOCOL["prompt_source"] = prompt_source
    rows = load_questions(assets["protocol_path"], assets.get("questions_file", "browsecomp-plus.tsv"))
    if len(rows) != assets.get("question_count", 830) or len({row[0] for row in rows}) != len(rows):
        raise RuntimeError("Unexpected or duplicate benchmark questions")
    if args.mode == "pilot":
        rows = pilot_questions(rows, int(os.environ.get("LRAT_EVAL_PILOT_SIZE", "16")))
        atomic_json(root / "pilot-selection.json", {"query_ids": [x[0] for x in rows], "seed": SEED})
    workers = int(os.environ.get("LRAT_EVAL_CONCURRENCY", "8"))
    output_dir = root / ("trajectories" if args.role == "agent" else "judgments")
    output_dir.mkdir(parents=True, exist_ok=True)
    remaining = [row for row in rows if not complete_file(output_dir / (row[0] + ".json"))]
    started = time.monotonic()
    errors = []
    if args.role == "agent":
        retriever = Retriever(assets, Path(os.environ["LRAT_EVAL_INDEX"]))
        agent_tokenizer = LockedTokenizer(AutoTokenizer.from_pretrained(assets["agent_path"], local_files_only=True))
        prompt = load_prompt(os.environ["LRAT_REPO_ROOT"], prompt_source,
                             "SYSTEM_PROMPT_SEARCH_ONLY")
    else:
        judge_template = load_prompt(os.environ["LRAT_REPO_ROOT"], "scripts_evaluation/evaluate.py", "JUDGE_TEMPLATE")

    client_setup_seconds = time.monotonic() - started
    started = time.monotonic()

    def process(row):
        qid, question, answer = row
        try:
            if args.role == "agent":
                result = run_agent(qid, question, retriever, agent_tokenizer, prompt,
                                   f"http://127.0.0.1:{args.port}/v1")
            else:
                agent_file = root / "trajectories" / (qid + ".json")
                if not complete_file(agent_file):
                    raise RuntimeError("Missing complete agent trajectory")
                trajectory = json.loads(agent_file.read_text())
                text = trajectory["prediction"]
                if not text or "<tool_call>" in text or "user_query" in text:
                    result = {"query_id": qid, "correct": False, "status": "no_answer", "judge_text": ""}
                else:
                    client = OpenAI(base_url=f"http://127.0.0.1:{args.port}/v1",
                                    api_key="EMPTY", timeout=600, max_retries=2)
                    judge_prompt = judge_template.format(question=question, response=text, correct_answer=answer)
                    for cap in (8192, 16384):
                        response = client.chat.completions.create(
                            model="lrat-eval-judge", messages=[{"role": "user", "content": judge_prompt}],
                            temperature=0, max_tokens=cap, seed=SEED,
                        )
                        content = response.choices[0].message.content or ""
                        correct = parse_judge(content)
                        if correct is not None:
                            break
                    client.close()
                    if correct is None:
                        raise RuntimeError("Judge response has no parseable correct: yes/no")
                    result = {"query_id": qid, "correct": correct, "status": "judged", "judge_text": content}
            atomic_json(output_dir / (qid + ".json"), result)
            return qid
        except Exception as exc:
            atomic_json(output_dir / (qid + ".json"), {
                "query_id": qid, "status": "infrastructure_error", "error": str(exc)})
            raise

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process, row): row[0] for row in remaining}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                future.result()
            except Exception as exc:
                errors.append({"query_id": futures[future], "error": str(exc)})
            print(f"{args.role}: completed {count}/{len(remaining)}, errors={len(errors)}", flush=True)
    elapsed = time.monotonic() - started
    timing = {"role": args.role, "mode": args.mode, "new_queries": len(remaining),
              "seconds": elapsed, "client_setup_seconds": client_setup_seconds, "workers": workers, "errors": errors}
    timing_path = root / (args.mode + "-" + args.role + "-timing.json")
    if remaining or not timing_path.exists():
        atomic_json(timing_path, timing)
    if errors:
        raise SystemExit(f"{len(errors)} infrastructure errors; refusing to report incomplete evaluation.")
    if args.role == "judge":
        qrels = defaultdict(set)
        has_qrels = benchmark == "BrowseComp-Plus"
        if has_qrels:
            with (Path(assets["protocol_path"]) / "qrel_evidence.txt").open() as file:
                for line in file:
                    qid, _, docid, _ = line.split()
                    qrels[qid].add(docid)
        details = []
        for qid, question, answer in rows:
            agent = json.loads((root / "trajectories" / (qid + ".json")).read_text())
            judgment = json.loads((root / "judgments" / (qid + ".json")).read_text())
            evidence = qrels[qid]
            found = set(agent["retrieved_docids"]) & evidence
            detail = {
                "query_id": qid, "correct": judgment["correct"],
                "steps": sum(agent["tool_call_counts"].values()),
                "model_calls": agent["model_calls"],
            }
            if has_qrels:
                detail.update(evidence_recall=len(found) / len(evidence) if evidence else 0,
                              any_evidence=bool(found))
            details.append(detail)
        metrics = aggregate_metrics(details, has_qrels)
        atomic_json(root / (args.mode + "-results.json"),
                    {"metrics": metrics, "queries": len(rows), "details": details, "protocol": PROTOCOL})
        print(json.dumps({"queries": len(rows), "metrics": metrics}, indent=2), flush=True)


if __name__ == "__main__":
    main()
