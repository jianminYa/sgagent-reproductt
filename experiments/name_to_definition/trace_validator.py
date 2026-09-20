"""Integrity and accounting checks for Phase3 official trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SECRET_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,})")
FORBIDDEN_TEXT = ("/workspace/proxy/.env", '"authorization":', '"x-api-key":')


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check_blob(value: Any, base: Path, errors: list[str], seen: set[str]) -> None:
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"}.issubset(value):
            rel = str(value["path"])
            if rel in seen:
                return
            seen.add(rel)
            blob = base / rel
            if not blob.exists():
                errors.append(f"missing sidecar: {rel}")
            else:
                data = blob.read_bytes()
                if len(data) != int(value["bytes"]):
                    errors.append(f"sidecar byte count mismatch: {rel}")
                if hashlib.sha256(data).hexdigest() != str(value["sha256"]):
                    errors.append(f"sidecar sha256 mismatch: {rel}")
                text = data.decode("utf-8", errors="replace")
                if SECRET_RE.search(text):
                    errors.append(f"credential-shaped text in sidecar: {rel}")
        for child in value.values():
            _check_blob(child, base, errors, seen)
    elif isinstance(value, list):
        for child in value:
            _check_blob(child, base, errors, seen)


def validate_trace(path: str | Path, summary_path: str | Path | None = None) -> dict[str, Any]:
    trajectory = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    if not trajectory.exists():
        return {"valid": False, "errors": [f"missing trajectory: {trajectory}"], "warnings": []}
    try:
        events = _events(trajectory)
    except Exception as exc:
        return {"valid": False, "errors": [f"invalid JSONL: {type(exc).__name__}: {exc}"], "warnings": []}
    sequences = [event.get("seq") for event in events]
    if sequences != list(range(1, len(events) + 1)):
        errors.append("event sequence is not continuous from 1")
    if not events or events[-1].get("event_type") != "final":
        errors.append("final event is missing or is not last")

    requests = [event for event in events if event.get("event_type") in {"llm_request", "nested_llm_request"}]
    responses = [event for event in events if event.get("event_type") in {"llm_response", "nested_llm_response"}]
    failures = [event for event in events if event.get("event_type") in {"llm_error", "nested_llm_error"}]
    for request in requests:
        key = (request.get("event_type"), request.get("phase"), request.get("call_index"))
        matched = any((response.get("event_type") == ("llm_response" if request["event_type"] == "llm_request" else "nested_llm_response")
                       and response.get("phase") == key[1]
                       and response.get("call_index") == key[2]) for response in responses)
        matched = matched or any((failure.get("event_type") == ("llm_error" if request["event_type"] == "llm_request" else "nested_llm_error")
                                  and failure.get("phase") == key[1]
                                  and failure.get("call_index") == key[2]) for failure in failures)
        if not matched:
            errors.append(f"LLM request has no response/error: {key}")

    tool_calls = [event for event in events if event.get("event_type") == "tool_call"]
    for index, event in enumerate(tool_calls, 1):
        if event.get("success"):
            if not event.get("result_ref") or not event.get("agent_return_ref"):
                errors.append(f"successful tool call {index} lacks complete result refs")
        elif not event.get("exception"):
            errors.append(f"failed tool call {index} lacks exception")

    serialized = trajectory.read_text(encoding="utf-8", errors="replace")
    for forbidden in FORBIDDEN_TEXT:
        if forbidden.lower() in serialized.lower():
            errors.append(f"forbidden credential/config marker in trajectory: {forbidden}")
    if SECRET_RE.search(serialized):
        errors.append("credential-shaped text in trajectory")
    seen: set[str] = set()
    for event in events:
        _check_blob(event, trajectory.parent, errors, seen)

    final = events[-1] if events and events[-1].get("event_type") == "final" else {}
    counters = final.get("aggregate_counters", {})
    expected = {
        "logical_llm_calls": len(requests),
        "http_attempts": sum(1 for event in events if event.get("event_type") == "llm_http_attempt"),
        "successful_llm_responses": len(responses),
        "tool_calls": sum(1 for event in tool_calls if event.get("success")),
        "failed_tool_calls": sum(1 for event in tool_calls if not event.get("success")),
    }
    for key, value in expected.items():
        if key in counters and counters[key] != value:
            errors.append(f"summary counter mismatch for {key}: {counters[key]} != {value}")
    if summary_path and Path(summary_path).exists():
        summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        for key in expected:
            if key in summary and summary[key] != expected[key]:
                errors.append(f"summary.json counter mismatch for {key}: {summary[key]} != {expected[key]}")
        summary_text = Path(summary_path).read_text(encoding="utf-8", errors="replace")
        if SECRET_RE.search(summary_text) or any(marker.lower() in summary_text.lower() for marker in FORBIDDEN_TEXT):
            errors.append("forbidden credential/config marker in summary.json")
    elif summary_path:
        warnings.append(f"missing summary file: {summary_path}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "event_count": len(events),
        "sidecars_checked": len(seen),
        "logical_llm_calls": len(requests),
        "http_attempts": expected["http_attempts"],
        "successful_llm_responses": len(responses),
        "tool_calls": expected["tool_calls"],
        "failed_tool_calls": expected["failed_tool_calls"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trajectory", nargs="+")
    parser.add_argument("--summary")
    args = parser.parse_args()
    results = [validate_trace(path, args.summary if len(args.trajectory) == 1 else None)
               for path in args.trajectory]
    print(json.dumps({"valid": all(result["valid"] for result in results), "results": results},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(result["valid"] for result in results) else 1)


if __name__ == "__main__":
    main()
