import json

import httpx
from langchain_core.messages import HumanMessage

from experiments.name_to_definition.full_tool_prompt import tool_system_template
from experiments.name_to_definition.official_locator import (
    DEFAULT_RETRY_BACKOFF_SECONDS,
    OfficialTrace,
    QtapiOfficialChat,
    OFFICIAL_TOOL_NAMES,
    _official_tool_names,
)
from experiments.name_to_definition.trace_validator import validate_trace


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.content = json.dumps(body).encode()
        self.headers = {"request-id": "req-test"}

    def json(self):
        return json.loads(self.content)


def test_request_level_retry_reuses_identical_body(monkeypatch, tmp_path):
    trace = OfficialTrace(tmp_path / "trajectory.jsonl", {"run_id": "test", "arm": "full14"})
    requests = []
    responses = [
        FakeResponse(502, {"error": {"type": "temporary"}}),
        FakeResponse(200, {
            "id": "resp-1", "model": "ep-64pmfvfo",
            "choices": [{"message": {"content": "INFO ENOUGH"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }),
    ]

    def fake_post(endpoint, headers, json, timeout):
        requests.append(json)
        return responses.pop(0)

    monkeypatch.setattr("experiments.name_to_definition.official_locator.httpx.post", fake_post)
    monkeypatch.setattr("experiments.name_to_definition.official_locator.time.sleep", lambda seconds: None)
    client = QtapiOfficialChat(
        "ep-64pmfvfo", "secret", "https://example.test/v1", 0.0, 3.0, trace,
        protocol="openai_chat_completions", request_retries=1, retry_backoff=(0.0,),
    )
    result = client.invoke([HumanMessage(content="hello")])
    trace.event("locator", "final", termination_reason="completed",
                aggregate_counters={"logical_llm_calls": 1, "http_attempts": 2,
                                    "successful_llm_responses": 1, "tool_calls": 0,
                                    "failed_tool_calls": 0})
    trace.close()
    assert result.content == "INFO ENOUGH"
    assert requests[0] == requests[1]
    events = [json.loads(line) for line in (tmp_path / "trajectory.jsonl").read_text().splitlines()]
    assert [event["status"] for event in events if event["event_type"] == "llm_http_attempt"] == [502, 200]
    assert sum(event["event_type"] == "llm_response" for event in events) == 1
    assert validate_trace(tmp_path / "trajectory.jsonl", tmp_path / "summary.json")["valid"]


def test_non_retryable_status_is_one_http_attempt(monkeypatch, tmp_path):
    trace = OfficialTrace(tmp_path / "trajectory.jsonl", {"run_id": "test", "arm": "full14"})
    monkeypatch.setattr(
        "experiments.name_to_definition.official_locator.httpx.post",
        lambda *args, **kwargs: FakeResponse(400, {"error": {"type": "invalid_request"}}),
    )
    client = QtapiOfficialChat(
        "ep-64pmfvfo", "secret", "https://example.test/v1", 0.0, 3.0, trace,
        protocol="openai_chat_completions", request_retries=3,
        retry_backoff=DEFAULT_RETRY_BACKOFF_SECONDS,
    )
    try:
        client.invoke([HumanMessage(content="hello")])
    except RuntimeError as exc:
        assert "HTTP 400" in str(exc)
    else:
        raise AssertionError("expected non-retryable provider error")
    trace.close()
    events = [json.loads(line) for line in (tmp_path / "trajectory.jsonl").read_text().splitlines()]
    assert len([event for event in events if event["event_type"] == "llm_http_attempt"]) == 1
    assert not any(event["event_type"] == "retry_scheduled" for event in events)


def test_full14_no_n2d_diff_is_exactly_two_tools_and_prompt_blocks():
    full = set(_official_tool_names("full14"))
    no_n2d = set(_official_tool_names("no_n2d"))
    assert full == set(OFFICIAL_TOOL_NAMES)
    assert full - no_n2d == {"find_methods_by_name", "find_all_variables_named"}
    assert no_n2d - full == set()
    full_prompt = tool_system_template("full14")
    no_prompt = tool_system_template("no_n2d")
    for name in full - {"find_methods_by_name", "find_all_variables_named"}:
        assert no_prompt.count(f'<tool name="{name}">') == 1
    for name in {"find_methods_by_name", "find_all_variables_named"}:
        assert full_prompt.count(f'<tool name="{name}">') == 1
        assert no_prompt.count(f'<tool name="{name}">') == 0


def test_trace_validator_detects_broken_sidecar(tmp_path):
    trace = OfficialTrace(tmp_path / "trajectory.jsonl", {"run_id": "test", "arm": "full14"})
    body_ref = trace.blob_json("request", {"messages": []})
    trace.event("locator", "llm_request", call_index=1, logical_call_index=1,
                request_body_ref=body_ref)
    trace.event("locator", "llm_error", call_index=1, logical_call_index=1,
                error_type="RuntimeError", error="temporary")
    trace.event("locator", "final", termination_reason="api_error",
                aggregate_counters={"logical_llm_calls": 1, "http_attempts": 0,
                                    "successful_llm_responses": 0, "tool_calls": 0,
                                    "failed_tool_calls": 0})
    trace.close()
    body_ref_path = tmp_path / body_ref["path"]
    body_ref_path.write_text("tampered", encoding="utf-8")
    result = validate_trace(tmp_path / "trajectory.jsonl")
    assert not result["valid"]
    assert any("sha256 mismatch" in error for error in result["errors"])
