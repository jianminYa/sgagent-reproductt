"""Run the one-shot Claude-3.5 connectivity preflight without credential output."""

from __future__ import annotations

import json
import os
import argparse
import time
from pathlib import Path

import httpx


DEFAULT_REPORT = Path("experiments/name_to_definition/reports/claude35_preflight/connectivity_report.json")
DEFAULT_MODEL = "claude-3.5-sonnet"


def _first_present(names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return name, value
    return None, None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args()
    requested_model = args.model
    report_path = Path(args.report)
    # The Phase 2A configuration contract names OPENAI_BASE_URL.  Keep the
    # Anthropic variable only as a compatibility fallback without exposing its
    # value.
    base_name, base_url = _first_present(("OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"))
    key_order = ("OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY") if base_name == "OPENAI_BASE_URL" else ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
    key_name, api_key = _first_present(key_order)
    report: dict[str, object] = {
        "schema_version": "1.0",
        "status": "failed",
        "protocol": "anthropic_messages",
        "requested_model": requested_model,
        "user_provided_model_mapping": "ep-64pmfvfo maps to Claude-3.5-Sonnet",
        "returned_model": None,
        "request_id": None,
        "stop_reason": None,
        "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
        "http_status": None,
        "credential_env_var": key_name,
        "credential_present": bool(api_key),
        "base_url_env_var": base_name,
        "base_url_present": bool(base_url),
        "api_key_recorded": False,
        "diagnosis": None,
        "latency_ms": None,
        "attempts": 0,
    }
    if not api_key or not base_url:
        report["diagnosis"] = "required credential or base URL variable is absent"
    else:
        openai_compatible = base_name == "OPENAI_BASE_URL"
        endpoint = base_url.rstrip("/")
        if openai_compatible:
            if not endpoint.endswith("/chat/completions"):
                endpoint += "/chat/completions" if endpoint.endswith("/v1") else "/v1/chat/completions"
            payload = {
                "model": requested_model,
                "max_tokens": 8,
                "temperature": 0.0,
                "messages": [
                    {"role": "system", "content": "Reply with exactly: PREFLIGHT_OK"},
                    {"role": "user", "content": "Return the requested fixed text."},
                ],
            }
            headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
            report["protocol"] = "openai_chat_completions"
        else:
            if not endpoint.endswith("/messages"):
                endpoint += "/v1/messages"
            payload = {
                "model": requested_model,
                "max_tokens": 8,
                "temperature": 0.0,
                "system": "Reply with exactly: PREFLIGHT_OK",
                "messages": [{"role": "user", "content": "Return the requested fixed text."}],
            }
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        started = time.monotonic()
        for attempt in range(1, max(0, args.max_retries) + 2):
            report["attempts"] = attempt
            try:
                response = httpx.post(endpoint, headers=headers, json=payload, timeout=60.0)
            except httpx.TimeoutException:
                report["diagnosis"] = "request timed out"
                break
            except httpx.HTTPError:
                report["diagnosis"] = "HTTP transport error; exception details intentionally omitted"
                break
            except Exception:
                report["diagnosis"] = "unexpected request error; exception details intentionally omitted"
                break
            report["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
            report["http_status"] = response.status_code
            if response.status_code >= 500 and attempt <= max(0, args.max_retries):
                continue
            try:
                body = response.json()
            except ValueError:
                report["diagnosis"] = "provider returned a non-JSON response"
            else:
                request_id = body.get("id") if isinstance(body, dict) else None
                if not request_id:
                    request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
                report["request_id"] = request_id
                report["returned_model"] = body.get("model") if isinstance(body, dict) else None
                usage = body.get("usage") or {} if isinstance(body, dict) else {}
                if openai_compatible:
                    input_tokens = usage.get("prompt_tokens")
                    output_tokens = usage.get("completion_tokens")
                    report["stop_reason"] = (
                        body.get("choices", [{}])[0].get("finish_reason")
                        if isinstance(body, dict) and body.get("choices")
                        else None
                    )
                    visible = (
                        body.get("choices", [{}])[0].get("message", {}).get("content", "")
                        if isinstance(body, dict) and body.get("choices")
                        else ""
                    )
                else:
                    input_tokens = usage.get("input_tokens")
                    output_tokens = usage.get("output_tokens")
                    report["stop_reason"] = body.get("stop_reason") if isinstance(body, dict) else None
                    visible = "\n".join(
                        str(block.get("text", ""))
                        for block in (body.get("content", []) if isinstance(body, dict) else [])
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                report["usage"] = {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": usage.get("total_tokens")
                    if isinstance(usage.get("total_tokens"), int)
                    else (input_tokens + output_tokens
                          if isinstance(input_tokens, int) and isinstance(output_tokens, int)
                          else None),
                }
                if response.status_code >= 400:
                    report["diagnosis"] = f"provider HTTP {response.status_code}; error body intentionally omitted"
                elif not report["returned_model"]:
                    report["diagnosis"] = "response did not identify a returned model"
                elif str(report["returned_model"]).strip() != requested_model:
                    report["diagnosis"] = "returned model differs from the requested alias; no underlying version inferred"
                elif visible.strip() != "PREFLIGHT_OK":
                    report["diagnosis"] = "response protocol succeeded but fixed-text check failed"
                else:
                    report["status"] = "success"
                    report["diagnosis"] = f"authenticated {report['protocol']} request returned the expected fixed text"
            break
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
