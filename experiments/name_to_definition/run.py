"""Locator-only paired runner with native tool calls and JSONL trajectories."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from . import EXPERIMENT_ID
from .index import RepositoryIndex
from .output_guard import protect_tool_output
from .repo import RepositoryManager
from .tools import ToolSpec, manifest_for_tools, tool_registry
from .tracing import TrajectoryWriter, extract_token_usage, monotonic_ms, serialize_message, sha256_json


LOCATION_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
TEXT_TOOL_RE = re.compile(r"#TOOL_CALL\s+([A-Za-z_][A-Za-z0-9_]*)\s+(\{.*?\})", re.DOTALL)


def _content(response: Any) -> str:
    value = getattr(response, "content", response)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in value)
    return str(value)


def _native_tool_calls(response: Any) -> list[dict[str, Any]]:
    calls = getattr(response, "tool_calls", None)
    if calls:
        return [{"id": c.get("id") or uuid.uuid4().hex, "name": c.get("name"), "args": c.get("args") or {}} for c in calls]
    calls = (getattr(response, "additional_kwargs", None) or {}).get("tool_calls", [])
    result = []
    for call in calls:
        fn = call.get("function", call)
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        result.append({"id": call.get("id") or uuid.uuid4().hex, "name": fn.get("name"), "args": args})
    if result:
        return result
    for name, raw in TEXT_TOOL_RE.findall(_content(response)):
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = {}
        result.append({"id": uuid.uuid4().hex, "name": name, "args": args, "text_protocol": True})
    return result


def parse_locations(text: str, root: Path) -> list[dict[str, int | str]]:
    candidates = [text.strip()]
    match = LOCATION_RE.search(text)
    if match:
        candidates.insert(0, match.group(1))
    # Accept a JSON object embedded in a short explanation while rejecting
    # arbitrary prose as a completed locator response.
    if "{" in text and "}" in text:
        start, end = text.find("{"), text.rfind("}")
        candidates.append(text[start:end + 1])
    decoded = None
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError):
            continue
    if not isinstance(decoded, dict) or not isinstance(decoded.get("locations"), list):
        raise ValueError("response is not a JSON object with a locations list")
    if len(decoded["locations"]) > 5:
        raise ValueError("locations list contains more than five entries")
    result = []
    for item in decoded["locations"]:
        if not isinstance(item, dict) or not isinstance(item.get("file_path"), str):
            raise ValueError("each location needs file_path, start_line, end_line")
        path = Path(item["file_path"])
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError("file_path is outside the repository") from exc
        rel = path.as_posix()
        if not rel or rel.startswith("../"):
            raise ValueError("file_path must be repository-relative")
        start, end = item.get("start_line"), item.get("end_line")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ValueError("line range is invalid")
        if not (root / path).is_file():
            raise ValueError(f"file does not exist: {rel}")
        line_count = len((root / path).read_text(encoding="utf-8", errors="replace").splitlines())
        if start > line_count:
            raise ValueError(f"start_line exceeds file: {rel}")
        result.append({"file_path": rel, "start_line": start, "end_line": min(end, line_count)})
    # Ranking is supplied by list order. Reject duplicate/overlapping entries
    # because the phase-one completion contract asks for distinct positions.
    seen = set()
    for loc in result:
        key = (loc["file_path"], loc["start_line"], loc["end_line"])
        if key in seen:
            raise ValueError("duplicate locations are not allowed")
        seen.add(key)
    return result


def _make_system(root: Path, tools: list[ToolSpec]) -> str:
    tool_lines = "\n".join(f"- {t.name}: {t.description}\n  schema: {json.dumps(t.parameters, ensure_ascii=False, sort_keys=True)}" for t in tools)
    return f"""You are SGAgent's Locator. Work only on the repository at {root}.
Your task is to locate the bug described by the issue, not to propose a patch.
Use the available tools to investigate. Tool results are evidence; do not invent files or line numbers.
If the issue contains a backticked or code-shaped identifier, use the exact name lookup tool when that tool is present in this registry; then use the shared content-reading tools to inspect any candidate. If no name lookup tool is present, use the shared search tools.
When you have enough evidence, return exactly a JSON object with at most five ranked repository-relative locations:
{{\"locations\":[{{\"file_path\":\"path/to/file.py\",\"start_line\":1,\"end_line\":10}}]}}
The list order is the relevance ranking. You may return an empty list only when no code location can be identified.
The following tool registry is the complete interface for this experimental arm:
{tool_lines}
Do not use tools not listed above. Do not output credentials, patches, or hidden reasoning."""


def _working_tree_hash() -> str:
    workspace = Path(__file__).resolve().parents[2]
    try:
        diff = subprocess.run(["git", "diff", "--binary"], cwd=workspace, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        staged = subprocess.run(["git", "diff", "--cached", "--binary"], cwd=workspace, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        # Include untracked source files, but exclude generated run/cache/data
        # directories whose contents change between the two arms.
        excluded = {"experiments/name_to_definition/runs", "experiments/name_to_definition/repo_cache",
                    "experiments/name_to_definition/manifests", ".pytest_cache"}
        status = subprocess.run(["git", "status", "--short", "--untracked-files=all"], cwd=workspace, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        chunks = [diff, staged]
        for line in status.splitlines():
            rel = line[3:] if len(line) > 3 else ""
            if any(rel == item or rel.startswith(item + "/") for item in excluded) or rel.endswith(".pyc"):
                continue
            path = workspace / rel
            if path.is_file():
                chunks.append(rel + "\0" + path.read_bytes().decode("utf-8", errors="replace"))
        return hashlib.sha256("\n".join(chunks).encode()).hexdigest()
    except Exception:
        return "unavailable"


class AnthropicCompatibleChat:
    """Small Claude Messages adapter for the qtapi configuration."""

    def __init__(self, model: str, api_key: str, base_url: str, tools: list[ToolSpec],
                 max_tokens: int, timeout: float):
        self.model, self.api_key, self.base_url = model, api_key, base_url.rstrip("/")
        self.tools, self.max_tokens, self.timeout = tools, max_tokens, timeout

    @staticmethod
    def _provider_messages(messages: list[Any]) -> tuple[str | None, list[dict[str, Any]]]:
        system = None; converted: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                system = str(message.content)
                continue
            if isinstance(message, ToolMessage):
                converted.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": message.tool_call_id, "content": str(message.content)}]})
                continue
            if isinstance(message, AIMessage):
                blocks: list[dict[str, Any]] = []
                content = _content(message)
                if content:
                    blocks.append({"type": "text", "text": content})
                for call in getattr(message, "tool_calls", None) or []:
                    blocks.append({"type": "tool_use", "id": call.get("id"), "name": call.get("name"), "input": call.get("args") or {}})
                converted.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
                continue
            converted.append({"role": "user", "content": str(message.content)})
        return system, converted

    def invoke(self, messages: list[Any]) -> AIMessage:
        system, provider_messages = self._provider_messages(messages)
        payload: dict[str, Any] = {"model": self.model, "max_tokens": self.max_tokens, "messages": provider_messages,
                                   "tools": [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in self.tools]}
        if system is not None:
            payload["system"] = system
        endpoint = self.base_url if self.base_url.endswith("/messages") else self.base_url + "/v1/messages"
        response = httpx.post(endpoint, headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                              json=payload, timeout=self.timeout)
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"provider returned non-JSON status {response.status_code}") from exc
        if response.status_code >= 400:
            error_type = body.get("error", {}).get("type", "provider_error") if isinstance(body, dict) else "provider_error"
            raise RuntimeError(f"provider returned HTTP {response.status_code}: {error_type}")
        blocks = body.get("content", [])
        text_parts = [str(block.get("text", "")) for block in blocks if block.get("type") == "text"]
        tool_calls = [{"name": block.get("name"), "args": block.get("input") or {}, "id": block.get("id")}
                      for block in blocks if block.get("type") == "tool_use"]
        usage = body.get("usage") or {}
        input_tokens = usage.get("input_tokens"); output_tokens = usage.get("output_tokens")
        token_usage = {"prompt_tokens": input_tokens, "completion_tokens": output_tokens,
                       "total_tokens": input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None}
        return AIMessage(content="\n".join(text_parts), tool_calls=tool_calls,
                         usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens,
                                         "total_tokens": token_usage["total_tokens"]},
                         response_metadata={"token_usage": token_usage, "stop_reason": body.get("stop_reason")})


class LocatorRunner:
    def __init__(self, row: dict[str, Any], arm: str, repo_root: Path, output_root: Path,
                 model: str, api_key: str, base_url: str, provider: str = "openai-compatible",
                 temperature: float = 0.0, max_turns: int = 12, timeout: float = 120,
                 max_output_tokens: int | None = None, fake_llm: Any = None,
                 index: RepositoryIndex | None = None, repeat: int = 0):
        self.row, self.arm, self.root = row, arm, repo_root
        self.output_root, self.model, self.api_key, self.base_url = output_root, model, api_key, base_url
        self.repeat = repeat
        self.provider, self.temperature, self.max_turns, self.timeout = provider, temperature, max_turns, timeout
        self.max_output_tokens, self.fake_llm = max_output_tokens, fake_llm
        self.index = index or RepositoryIndex(repo_root)
        self.tools = tool_registry(self.index, arm)
        self.tool_map = {tool.name: tool for tool in self.tools}
        self.manifest = manifest_for_tools(self.tools)
        self.run_id = f"{EXPERIMENT_ID}-{row['instance_id']}-{arm}-{uuid.uuid4().hex[:10]}"
        self.trajectory_path = output_root / arm / str(row["instance_id"]) / str(repeat) / "trajectory.jsonl"
        static = {
            "run_id": self.run_id, "experiment_id": EXPERIMENT_ID, "instance_id": row["instance_id"],
            "arm": arm, "repeat": repeat, "sampling_seed": 20260915,
            "sgagent_commit": "33a2cfe61d56494ab2d20a2b0c48c1f43e37b452",
            "working_tree_diff_hash": _working_tree_hash(),
            "repo": row["repo"], "repo_commit": row["base_commit"],
            "dataset_id": "SWE-Explore ∩ SWE-bench Verified",
            "dataset_revision": "local-commit-33a2cfe",
            "model": model, "provider": provider, "temperature": temperature,
            "budgets": {"max_turns": max_turns, "timeout_seconds": timeout, "max_output_tokens": max_output_tokens},
            "prompt_hash": sha256_json(_make_system(repo_root, self.tools)),
            "tool_manifest": self.manifest, "tool_manifest_hash": sha256_json(self.manifest),
            "index_hash": self.index.index_hash,
        }
        self.tracer = TrajectoryWriter(self.trajectory_path, static)

    def _invoke(self, llm: Any, messages: list[Any]) -> Any:
        if self.timeout <= 0:
            return llm.invoke(messages)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(llm.invoke, messages)
            return future.result(timeout=self.timeout)

    def _llm(self) -> Any:
        if self.fake_llm is not None:
            return self.fake_llm
        if self.provider == "anthropic" or "cdn.qtapi.net" in self.base_url:
            return AnthropicCompatibleChat(self.model, self.api_key, self.base_url, self.tools,
                                           self.max_output_tokens or 1200, self.timeout)
        kwargs = {"model": self.model, "temperature": self.temperature, "api_key": self.api_key,
                  "base_url": self.base_url, "timeout": self.timeout, "max_retries": 0}
        if self.max_output_tokens is not None:
            kwargs["max_tokens"] = self.max_output_tokens
        llm = ChatOpenAI(**kwargs)
        return llm.bind_tools(self.manifest)

    def run(self) -> dict[str, Any]:
        start_run = time.monotonic()
        counters = {"locator_llm_calls": 0, "tool_calls": 0, "failed_tool_calls": 0,
                    "reflection_turns": 0, "summarizer_llm_calls": 0, "total_llm_calls": 0,
                    "tool_result_chars": 0, "tool_original_chars": 0,
                    "tool_returned_chars": 0, "truncated_tool_calls": 0,
                    "token_usage_incomplete": False,
                    "input_tokens": None, "output_tokens": None, "total_tokens": None}
        input_token_values: list[int] = []; output_token_values: list[int] = []; total_token_values: list[int] = []
        first_round_usage: dict[str, Any] | None = None; later_round_usage: list[dict[str, Any]] = []
        termination_reason = "budget_exhausted"
        locations: list[dict[str, Any]] = []
        system = _make_system(self.root, self.tools)
        messages: list[Any] = [SystemMessage(content=system), HumanMessage(content=(
            f"Issue description for {self.row['instance_id']}:\n{self.row['problem_statement']}\n\n"
            "Begin investigation. At completion, return the required JSON locations object."
        ))]
        self.tracer.event("locator", "run_start", start_timestamp=time.time(), index_file_count=len(self.index.files))
        llm = self._llm()
        try:
            for turn in range(1, self.max_turns + 1):
                req_start = time.monotonic()
                request_messages = [serialize_message(m) for m in messages]
                self.tracer.event("locator", "llm_request", turn=turn, messages=request_messages,
                                  prompt_hash=sha256_json(request_messages))
                try:
                    response = self._invoke(llm, messages)
                except concurrent.futures.TimeoutError as exc:
                    termination_reason = "timeout"
                    self.tracer.event("locator", "llm_error", turn=turn, error_type=type(exc).__name__, error=str(exc), latency_ms=monotonic_ms(req_start))
                    break
                except Exception as exc:
                    termination_reason = "api_error"
                    self.tracer.event("locator", "llm_error", turn=turn, error_type=type(exc).__name__, error=str(exc), latency_ms=monotonic_ms(req_start))
                    break
                counters["locator_llm_calls"] += 1; counters["total_llm_calls"] += 1
                usage = extract_token_usage(response)
                counters["token_usage_incomplete"] |= not usage["complete"]
                if usage["input_tokens"] is not None: input_token_values.append(usage["input_tokens"])
                if usage["output_tokens"] is not None: output_token_values.append(usage["output_tokens"])
                if usage["total_tokens"] is not None: total_token_values.append(usage["total_tokens"])
                if turn == 1: first_round_usage = usage
                else: later_round_usage.append(usage)
                self.tracer.event("locator", "llm_response", turn=turn, response=serialize_message(response),
                                  visible_content=_content(response), token_usage=usage, latency_ms=monotonic_ms(req_start))
                calls = _native_tool_calls(response)
                messages.append(response)
                if calls:
                    tool_failed = False
                    for call in calls:
                        name, args, call_start = call.get("name"), call.get("args", {}), time.monotonic()
                        tool = self.tool_map.get(name)
                        if tool is None:
                            counters["failed_tool_calls"] += 1
                            error = f"unknown tool: {name}"
                            self.tracer.event("locator", "tool_call", tool_name=name, arguments=args, success=False,
                                              exception=error, result=None, result_chars=0, latency_ms=monotonic_ms(call_start))
                            messages.append(ToolMessage(content=error, tool_call_id=call.get("id"), name=name or "unknown"))
                            termination_reason = "tool_error"
                            tool_failed = True
                            break
                        try:
                            result = tool.fn(**args)
                            protected = protect_tool_output(name, result, args)
                            result_text = protected.text
                            counters["tool_calls"] += 1; counters["tool_result_chars"] += len(result_text)
                            counters["tool_original_chars"] += protected.original_chars
                            counters["tool_returned_chars"] += protected.returned_chars
                            counters["truncated_tool_calls"] += int(protected.truncated)
                            self.tracer.event("locator", "tool_call", tool_name=name, arguments=args, success=True,
                                              result=result_text, result_chars=protected.returned_chars,
                                              original_chars=protected.original_chars, returned_chars=protected.returned_chars,
                                              truncated=protected.truncated, latency_ms=monotonic_ms(call_start))
                            messages.append(ToolMessage(content=result_text, tool_call_id=call.get("id"), name=name))
                        except Exception as exc:
                            counters["failed_tool_calls"] += 1
                            error = f"tool execution error ({type(exc).__name__}): {exc}"
                            self.tracer.event("locator", "tool_call", tool_name=name, arguments=args, success=False,
                                              exception=error, result=None, result_chars=0, latency_ms=monotonic_ms(call_start))
                            messages.append(ToolMessage(content=error, tool_call_id=call.get("id"), name=name))
                            termination_reason = "tool_error"
                            tool_failed = True
                            break
                    if tool_failed:
                        break
                    continue
                try:
                    locations = parse_locations(_content(response), self.root)
                    termination_reason = "completed"
                    self.tracer.event("locator", "locator_output", locations=locations, ranked=True, parseable=True)
                    break
                except Exception as exc:
                    counters["reflection_turns"] += 1
                    self.tracer.event("locator", "parse_error", turn=turn, error_type=type(exc).__name__, error=str(exc), visible_response=_content(response))
                    messages.append(HumanMessage(content=(
                        "Your last response was not a valid locator result. Continue investigating or return exactly "
                        "a JSON object {\"locations\":[{\"file_path\":\"repo/relative.py\",\"start_line\":1,\"end_line\":2}]} with at most five entries."
                    )))
            if termination_reason == "budget_exhausted" and counters["locator_llm_calls"] >= self.max_turns:
                termination_reason = "budget_exhausted"
        finally:
            counters["token_usage_incomplete"] |= counters["locator_llm_calls"] == 0
            summary = {"locations": locations, "termination_reason": termination_reason,
                       **counters, "wall_clock_ms": monotonic_ms(start_run),
                       "input_tokens": sum(input_token_values) if counters["locator_llm_calls"] and len(input_token_values) == counters["locator_llm_calls"] else None,
                       "output_tokens": sum(output_token_values) if counters["locator_llm_calls"] and len(output_token_values) == counters["locator_llm_calls"] else None,
                       "total_tokens": sum(total_token_values) if counters["locator_llm_calls"] and len(total_token_values) == counters["locator_llm_calls"] else None,
                       "first_round_token_usage": first_round_usage,
                       "later_round_token_usage": later_round_usage}
            self.tracer.event("locator", "final", ranked_locations=locations, termination_reason=termination_reason,
                              aggregate_counters=summary)
            self.tracer.close()
            self.trajectory_path.with_name("summary.json").write_text(
                json.dumps({"schema_version": "1.0", "run_id": self.run_id, **summary}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return {"run_id": self.run_id, "instance_id": self.row["instance_id"], "arm": self.arm,
                "trajectory_path": str(self.trajectory_path), **summary}


def _load_rows(manifest_path: Path, verified_path: Path) -> dict[str, dict[str, Any]]:
    import pandas as pd
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    df = pd.read_parquet(verified_path)
    by_id = {str(row.instance_id): row._asdict() for row in df.itertuples(index=False)}
    result = {}
    for item in manifest["instances"]:
        row = by_id.get(str(item["instance_id"]))
        if row is None:
            raise KeyError(f"instance not found in verified dataset: {item['instance_id']}")
        result[str(item["instance_id"])] = {**item, **row}
    return result


def _next_attempt(output_root: Path, arm: str, instance_id: str, resume: bool) -> int | None:
    instance_root = output_root / arm / str(instance_id)
    attempts = sorted(int(path.name) for path in instance_root.iterdir() if path.is_dir() and path.name.isdigit()) if instance_root.exists() else []
    if not attempts:
        return 0
    for attempt in reversed(attempts):
        path = instance_root / str(attempt) / "trajectory.jsonl"
        if path.exists():
            try:
                last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
                if last.get("event_type") == "final":
                    return None if resume else attempt + 1
            except (ValueError, IndexError, json.JSONDecodeError):
                pass
    return max(attempts) + 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verified", default="dataset/verified.parquet")
    parser.add_argument("--arms", default="baseline,n2d")
    parser.add_argument("--locator-only", action="store_true", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--source-root")
    parser.add_argument("--repo-cache", default="experiments/name_to_definition/repo_cache")
    parser.add_argument("--output-root", default="experiments/name_to_definition/runs/name_to_definition_phase1")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "claude-sonnet-5"))
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://cdn.qtapi.net"))
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "anthropic"), choices=["anthropic", "openai-compatible"])
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if not args.locator_only:
        parser.error("phase-one runner only supports --locator-only")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise SystemExit("missing API key: inject it from a secure local config; it is never read from the manifest")
    rows = _load_rows(Path(args.manifest), Path(args.verified))
    manager = RepositoryManager(args.repo_cache, args.source_root)
    output_root = Path(args.output_root)
    run_rows = list(rows.values())[:args.limit] if args.limit else list(rows.values())
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    results = []

    def run_instance(task: tuple[int, dict[str, Any]]) -> list[dict[str, Any]]:
        idx, row = task
        order = arms if idx % 2 == 0 else list(reversed(arms))
        instance_results = []
        with manager.materialize(str(row["repo"]), str(row["base_commit"])) as repo_root:
            index = RepositoryIndex(repo_root)
            for arm in order:
                repeat = _next_attempt(output_root, arm, str(row["instance_id"]), args.resume)
                if repeat is None:
                    print(json.dumps({"skipped": str(row["instance_id"]), "arm": arm}))
                    continue
                result = LocatorRunner(row, arm, repo_root, output_root, args.model, api_key,
                                       args.base_url, provider=args.provider, max_turns=args.max_turns, timeout=args.timeout,
                                       max_output_tokens=args.max_output_tokens, index=index, repeat=repeat).run()
                instance_results.append(result)
                print(json.dumps({"instance_id": row["instance_id"], "arm": arm, "termination_reason": result["termination_reason"],
                                  "llm_calls": result["locator_llm_calls"], "tool_calls": result["tool_calls"]}, ensure_ascii=False))
        return instance_results
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        for instance_results in executor.map(run_instance, enumerate(run_rows)):
            results.extend(instance_results)
    summary_path = output_root / "run_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
