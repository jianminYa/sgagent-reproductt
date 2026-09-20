from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage

from experiments.name_to_definition.fake import FakeLLM
from experiments.name_to_definition.index import RepositoryIndex
from experiments.name_to_definition.run import LocatorRunner, parse_locations
from experiments.name_to_definition.tools import COMMON_TOOL_NAMES, N2D_TOOL_NAMES, tool_registry
from experiments.name_to_definition.tracing import extract_token_usage


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "model.py").write_text(
        "class User:\n"
        "    value = 1\n\n"
        "    def save(self, update_fields=None):\n"
        "        return update_fields\n\n"
        "def save(value):\n"
        "    return value\n", encoding="utf-8"
    )
    return root


def _row():
    return {"instance_id": "fake__fake-1", "repo": "fake/fake", "base_commit": "deadbeef",
            "problem_statement": "The save method fails."}


def test_n2d_exact_substring_pagination_and_no_body(tmp_path):
    index = RepositoryIndex(_repo(tmp_path))
    methods = index.definitions("method", "save")
    assert len(methods) == 2
    assert all("content" not in c and "relationships" not in c for c in methods)
    page = index.candidate_page("method", "sav", top_k=1, match_mode="substring")
    assert page["match_mode"] == "substring"
    assert page["total_candidates"] == 2
    assert page["next_cursor"] == 1
    assert len(index.candidate_page("method", "save", top_k=1, cursor=1)["candidates"]) == 1


def test_arm_isolation_and_common_tools(tmp_path):
    registry = tool_registry(RepositoryIndex(_repo(tmp_path)), "baseline")
    assert [t.name for t in registry] == list(COMMON_TOOL_NAMES)
    registry = tool_registry(RepositoryIndex(_repo(tmp_path)), "n2d")
    assert [t.name for t in registry] == list(COMMON_TOOL_NAMES) + list(N2D_TOOL_NAMES)
    assert "execute_shell_command_with_validation" not in {t.name for t in registry}


def test_locator_fake_integration_and_replay(tmp_path):
    root = _repo(tmp_path)
    baseline_llm = FakeLLM([
        AIMessage(content="", tool_calls=[{"name": "search_code_with_context", "args": {"keyword": "save", "search_path": "."}, "id": "b1"}]),
        '{"locations":[{"file_path":"pkg/model.py","start_line":5,"end_line":6}]}',
    ])
    n2d_llm = FakeLLM([
        AIMessage(content="", tool_calls=[{"name": "find_methods_by_name", "args": {"name": "save"}, "id": "n1"}]),
        '{"locations":[{"file_path":"pkg/model.py","start_line":5,"end_line":6}]}',
    ])
    out = tmp_path / "runs"
    results = []
    for arm, fake in [("baseline", baseline_llm), ("n2d", n2d_llm)]:
        result = LocatorRunner(_row(), arm, root, out, "fake", "fake", "http://fake", fake_llm=fake, max_turns=3).run()
        results.append(result)
        assert result["termination_reason"] == "completed"
        assert result["token_usage_incomplete"] is True
        assert result["tool_calls"] == 1
        events = [json.loads(line) for line in (out / arm / _row()["instance_id"] / "0" / "trajectory.jsonl").read_text().splitlines()]
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert events[-1]["event_type"] == "final"
    assert results[0]["tool_calls"] == results[1]["tool_calls"]


def test_baseline_cannot_call_n2d(tmp_path):
    root = _repo(tmp_path); out = tmp_path / "runs"
    fake = FakeLLM([AIMessage(content="", tool_calls=[{"name": "find_methods_by_name", "args": {"name": "save"}, "id": "x"}]), '{"locations":[]}'])
    result = LocatorRunner(_row(), "baseline", root, out, "fake", "fake", "http://fake", fake_llm=fake, max_turns=2).run()
    assert result["failed_tool_calls"] == 1
    assert result["termination_reason"] == "tool_error"
    events = [json.loads(line) for line in (out / "baseline" / _row()["instance_id"] / "0" / "trajectory.jsonl").read_text().splitlines()]
    assert any(e.get("event_type") == "tool_call" and e.get("success") is False for e in events)


def test_parse_locations_and_token_fallback(tmp_path):
    root = _repo(tmp_path)
    assert parse_locations('```json\n{"locations":[]}\n```', root) == []
    class Response:
        usage_metadata = {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
        response_metadata = {}
    assert extract_token_usage(Response())["total_tokens"] == 7
    assert extract_token_usage(AIMessage(content="x"))["complete"] is False
