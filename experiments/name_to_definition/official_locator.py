"""Run the repository's official Locator workflow with a qtapi adapter.

The public SGAgent workflow remains the source of agent behavior.  This module
only supplies a Claude Messages transport, trajectory tracing, immutable source
materialization, and a stop after the first successful Locator output.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda

from . import SCHEMA_VERSION
from .full_tool_prompt import FULL_TOOL_SYSTEM_TEMPLATE, N2D_TOOL_NAMES, tool_system_template
from .output_guard import protect_tool_output
from .repo import RepositoryManager
from .tracing import SidecarStore, TrajectoryWriter, monotonic_ms, redact, serialize_message, sha256_json


UPSTREAM_COMMIT = "33a2cfe61d56494ab2d20a2b0c48c1f43e37b452"
OFFICIAL_TOOL_NAMES = (
    "explore_directory", "analyze_file_structure", "find_files_containing",
    "get_code_relationships", "find_methods_by_name", "extract_complete_method",
    "find_class_constructor", "list_class_attributes", "show_file_imports",
    "find_variable_usage", "find_all_variables_named", "read_file_lines",
    "search_code_with_context", "execute_shell_command_with_validation",
)
OFFICIAL_TOOL_NAMES = tuple(OFFICIAL_TOOL_NAMES)
OFFICIAL_ARM_NAMES = ("full14", "no_n2d")
DEFAULT_REQUEST_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = (15.0, 30.0, 60.0)
REQUEST_MAX_TOKENS = 8192


def _content(response: Any) -> str:
    value = getattr(response, "content", response)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in value)
    return str(value)


def _working_tree_hash() -> str:
    workspace = Path(__file__).resolve().parents[2]
    try:
        diff = subprocess.run(["git", "diff", "--binary"], cwd=workspace, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        staged = subprocess.run(["git", "diff", "--cached", "--binary"], cwd=workspace, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        excluded = {"experiments/name_to_definition/runs", "experiments/name_to_definition/repo_cache",
                    "experiments/name_to_definition/manifests", ".pytest_cache"}
        status = subprocess.run(["git", "status", "--short", "--untracked-files=all"], cwd=workspace,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
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


def _install_python313_lib2to3_stub() -> None:
    """Keep official AST behavior on Python 3.13 where lib2to3 was removed.

    The official parser uses lib2to3 only as a syntax-error fallback.  Normal
    AST parsing remains unchanged; the fallback is explicitly unavailable in
    this runtime and is recorded in the reproduction gap report.
    """
    try:
        __import__("lib2to3.refactor")
        return
    except ModuleNotFoundError:
        pass
    package = types.ModuleType("lib2to3")
    refactor = types.ModuleType("lib2to3.refactor")

    class RefactoringTool:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def refactor_string(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("lib2to3 is unavailable in Python 3.13")

    refactor.RefactoringTool = RefactoringTool
    refactor.get_fixers_from_package = lambda package_name: []
    package.refactor = refactor
    sys.modules["lib2to3"] = package
    sys.modules["lib2to3.refactor"] = refactor


def _safe_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_text_tool_calls(content: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in re.finditer(r"#TOOL_CALL\s+(\w+)\s+({.*?})", content, re.DOTALL):
        raw = match.group(0)
        try:
            arguments = json.loads(match.group(2))
            parse_error = None
        except json.JSONDecodeError as exc:
            arguments = {}
            parse_error = f"JSONDecodeError: {exc.msg}"
        calls.append({"name": match.group(1), "arguments": arguments,
                      "raw_text": raw, "parse_error": parse_error})
    return calls


def _official_tool_names(arm: str) -> tuple[str, ...]:
    if arm == "full14":
        return OFFICIAL_TOOL_NAMES
    if arm == "no_n2d":
        return tuple(name for name in OFFICIAL_TOOL_NAMES if name not in N2D_TOOL_NAMES)
    raise ValueError(f"unknown official arm: {arm}")


def _phase(messages: list[Any]) -> str:
    joined = "\n".join(str(getattr(m, "content", "")) for m in messages)
    if "<locator_role>" in joined:
        return "locator"
    if "<suggester_role>" in joined:
        return "suggester"
    if "<fixer_role>" in joined:
        return "fixer"
    return "summarizer"


def _provider_messages(messages: list[Any]) -> tuple[str | None, list[dict[str, Any]]]:
    system = None
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            system = str(message.content)
        elif isinstance(message, AIMessage):
            converted.append({"role": "assistant", "content": _content(message)})
        else:
            converted.append({"role": "user", "content": str(message.content)})
    return system, converted


class OfficialTrace:
    def __init__(self, path: Path, static: dict[str, Any]):
        self.writer = TrajectoryWriter(path, static)
        self.sidecars = SidecarStore(path)
        self.records: list[dict[str, Any]] = []
        self.pending_tool_calls: list[dict[str, Any]] = []
        self._nested_indices: dict[str, int] = {}

    def event(self, phase: str, event_type: str, **payload: Any) -> dict[str, Any]:
        record = self.writer.event(phase, event_type, **payload)
        self.records.append(record)
        return record

    def blob_text(self, label: str, value: Any) -> dict[str, Any]:
        return self.sidecars.put_text(label, value)

    def blob_json(self, label: str, value: Any) -> dict[str, Any]:
        return self.sidecars.put_json(label, value)

    @staticmethod
    def serialize_message(message: Any) -> dict[str, Any]:
        return serialize_message(message)

    def agent_event(self, event_type: str, phase: str, **payload: Any) -> None:
        if "content" in payload:
            payload["content_ref"] = self.blob_text(f"agent-{event_type}", payload.pop("content"))
        self.event(phase.lower(), event_type, **payload)

    def nested_event(self, event_type: str, **payload: Any) -> None:
        phase = str(payload.get("phase", "shell_validation"))
        if event_type == "nested_llm_request":
            index = self._nested_indices.get(phase, 0) + 1
            self._nested_indices[phase] = index
            messages = payload.pop("messages", [])
            request_body = {
                "model": payload.get("model"), "messages": messages,
                "temperature": payload.get("temperature"),
            }
            payload["call_index"] = index
            payload["messages_ref"] = self.blob_json("nested-messages", messages)
            payload["request_body_ref"] = self.blob_json("nested-request", request_body)
            payload["request_hash"] = sha256_json(request_body)
        elif event_type in {"nested_llm_response", "nested_llm_error"}:
            payload.setdefault("call_index", self._nested_indices.get(phase, 0))
            if "visible_content" in payload:
                payload["visible_content_ref"] = self.blob_text("nested-response", payload.pop("visible_content"))
        self.event(phase, event_type, **payload)

    def close(self) -> None:
        self.writer.close()


class QtapiOfficialChat:
    """Qtapi transport without native tools, matching the textual protocol."""

    def __init__(self, model: str, api_key: str, base_url: str, temperature: float,
                 timeout: float, trace: OfficialTrace, protocol: str = "anthropic_messages",
                 request_retries: int = DEFAULT_REQUEST_RETRIES,
                 retry_backoff: tuple[float, ...] = DEFAULT_RETRY_BACKOFF_SECONDS):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.trace = trace
        self.protocol = protocol
        self.request_retries = request_retries
        self.retry_backoff = tuple(retry_backoff)
        self.calls_by_phase: dict[str, int] = {}

    def invoke(self, messages: Any) -> AIMessage:
        if hasattr(messages, "to_messages"):
            messages = messages.to_messages()
        messages = list(messages)
        phase = _phase(messages)
        call_index = self.calls_by_phase.get(phase, 0) + 1
        self.calls_by_phase[phase] = call_index
        serialized = [serialize_message(message) for message in messages]
        system, provider_messages = _provider_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": provider_messages,
            "temperature": self.temperature,
            # Anthropic requires max_tokens even though the official code does
            # not impose a max-output setting.  This is a transport parameter,
            # recorded as such rather than treated as an experiment budget.
            "max_tokens": REQUEST_MAX_TOKENS,
        }
        if self.protocol == "openai_chat_completions" and system is not None:
            payload["messages"] = [{"role": "system", "content": system}] + provider_messages
        elif system is not None:
            payload["system"] = system
        if self.protocol == "openai_chat_completions":
            endpoint = self.base_url if self.base_url.endswith("/chat/completions") else (
                self.base_url + "/chat/completions" if self.base_url.endswith("/v1")
                else self.base_url + "/v1/chat/completions"
            )
            headers = {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        else:
            endpoint = self.base_url if self.base_url.endswith("/messages") else self.base_url + "/v1/messages"
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        request_ref = self.trace.blob_json("llm-request-body", payload)
        messages_ref = self.trace.blob_json("llm-messages", serialized)
        request_hash = sha256_json(payload)
        self.trace.event(
            phase, "llm_request", call_index=call_index,
            logical_call_index=call_index, requested_model=self.model,
            protocol=self.protocol, messages_ref=messages_ref,
            request_body_ref=request_ref, prompt_hash=sha256_json(serialized),
            request_hash=request_hash,
            request_parameters={"model": self.model, "temperature": self.temperature,
                                "max_tokens": REQUEST_MAX_TOKENS,
                                "native_tools": False, "protocol": self.protocol},
            retry_policy={"max_additional_retries": self.request_retries,
                          "backoff_seconds": list(self.retry_backoff),
                          "retryable_statuses": [502, 503, 504],
                          "retryable_network_errors": ["httpx.TimeoutException", "httpx.NetworkError"]},
            request_start_utc=_utc_now(),
        )

        response = None
        body = None
        raw_body_text = ""
        attempt_count = 0
        last_error: Exception | None = None
        max_attempts = 1 + self.request_retries
        for attempt_index in range(1, max_attempts + 1):
            attempt_count = attempt_index
            attempt_started = time.monotonic()
            attempt_start_utc = _utc_now()
            attempt_status = None
            attempt_error_type = None
            attempt_error = None
            response_ref = None
            retry_scheduled = False
            backoff_seconds = 0.0
            try:
                # The exact same Python payload object is sent on every
                # attempt; no trajectory state is rebuilt between retries.
                response = httpx.post(endpoint, headers=headers, json=payload, timeout=self.timeout)
                attempt_status = int(response.status_code)
                raw_bytes = getattr(response, "content", b"")
                if not raw_bytes:
                    try:
                        raw_bytes = json.dumps(response.json(), ensure_ascii=False,
                                               sort_keys=True, default=str).encode("utf-8")
                    except Exception:
                        raw_bytes = b""
                raw_body_text = raw_bytes.decode("utf-8", errors="replace")
                response_ref = self.trace.blob_text("llm-http-response", raw_body_text)
                if attempt_status in {502, 503, 504}:
                    if attempt_index < max_attempts:
                        retry_scheduled = True
                    else:
                        attempt_error_type = "provider_error"
                        attempt_error = f"HTTP {attempt_status}: retry budget exhausted"
                        raise RuntimeError(f"provider returned HTTP {attempt_status}")
                elif attempt_status >= 400:
                    try:
                        candidate = response.json()
                    except ValueError as exc:
                        attempt_error_type = "parse_error"
                        attempt_error = "provider error body was not JSON"
                        raise RuntimeError(f"provider returned non-JSON status {attempt_status}") from exc
                    error_type = (candidate.get("error", {}).get("type", "provider_error")
                                  if isinstance(candidate, dict) else "provider_error")
                    attempt_error_type = "provider_error"
                    attempt_error = f"HTTP {attempt_status}: {error_type}"
                    raise RuntimeError(f"provider returned HTTP {attempt_status}: {error_type}")
                if not retry_scheduled:
                    try:
                        body = response.json()
                    except ValueError as exc:
                        attempt_error_type = "parse_error"
                        attempt_error = "successful HTTP response was not JSON"
                        raise RuntimeError(f"provider returned non-JSON status {attempt_status}") from exc
                    if not isinstance(body, dict):
                        attempt_error_type = "parse_error"
                        attempt_error = "provider JSON response was not an object"
                        raise RuntimeError("provider returned an invalid JSON object")
                    self.trace.event(
                        phase, "llm_http_attempt", call_index=call_index,
                        logical_call_index=call_index, attempt_index=attempt_index,
                        attempt_start_utc=attempt_start_utc, attempt_end_utc=_utc_now(),
                        status=attempt_status, latency_ms=monotonic_ms(attempt_started),
                        request_hash=request_hash, response_body_ref=response_ref,
                        error_type=None, error=None, retry_scheduled=False,
                        backoff_seconds=0.0,
                    )
                    break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                attempt_error_type = type(exc).__name__
                attempt_error = str(exc)
                if attempt_index >= max_attempts:
                    break
                retry_scheduled = True
            except Exception as exc:
                last_error = exc
                if attempt_error_type is None:
                    attempt_error_type = type(exc).__name__
                    attempt_error = str(exc)
                # HTTP errors, parse errors, and model errors are not retryable
                # except for the explicit 502/503/504 branch above.
                if attempt_status not in {502, 503, 504} or attempt_index >= max_attempts:
                    retry_scheduled = False
                    self.trace.event(
                        phase, "llm_http_attempt", call_index=call_index,
                        logical_call_index=call_index, attempt_index=attempt_index,
                        attempt_start_utc=attempt_start_utc, attempt_end_utc=_utc_now(),
                        status=attempt_status, latency_ms=monotonic_ms(attempt_started),
                        request_hash=request_hash, response_body_ref=response_ref,
                        error_type=attempt_error_type, error=attempt_error,
                        retry_scheduled=False, backoff_seconds=0.0,
                    )
                    break
            finally:
                # A retryable HTTP status reaches this finally block after the
                # normal response path; the common event below records it once.
                pass

            if retry_scheduled:
                backoff_seconds = self.retry_backoff[min(attempt_index - 1, len(self.retry_backoff) - 1)] if self.retry_backoff else 0.0
            self.trace.event(
                phase, "llm_http_attempt", call_index=call_index,
                logical_call_index=call_index, attempt_index=attempt_index,
                attempt_start_utc=attempt_start_utc, attempt_end_utc=_utc_now(),
                status=attempt_status, latency_ms=monotonic_ms(attempt_started),
                request_hash=request_hash, response_body_ref=response_ref,
                error_type=attempt_error_type, error=attempt_error,
                retry_scheduled=retry_scheduled, backoff_seconds=backoff_seconds,
            )
            if retry_scheduled:
                self.trace.event(phase, "retry_scheduled", call_index=call_index,
                                 logical_call_index=call_index, attempt_index=attempt_index,
                                 reason=f"HTTP {attempt_status}" if attempt_status else attempt_error_type,
                                 backoff_seconds=backoff_seconds)
                time.sleep(backoff_seconds)
                continue
            break

        if body is None:
            error = last_error or RuntimeError("provider request failed")
            self.trace.event(phase, "llm_error", call_index=call_index,
                             logical_call_index=call_index,
                             error_type=type(error).__name__, error=str(error),
                             http_attempts=attempt_count, request_hash=request_hash,
                             latency_ms=0.0)
            raise error

        request_id = body.get("id") if isinstance(body, dict) else None
        if not request_id:
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
        returned_model = body.get("model") if isinstance(body, dict) else None
        stop_reason = body.get("stop_reason") if isinstance(body, dict) else None
        if self.protocol == "openai_chat_completions":
            choice = (body.get("choices") or [{}])[0] if isinstance(body, dict) else {}
            message = choice.get("message") or {}
            visible = _content(message.get("content", "")) if isinstance(message, dict) else ""
            stop_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
        else:
            blocks = body.get("content", []) if isinstance(body, dict) else []
            visible = "\n".join(str(block.get("text", "")) for block in blocks if block.get("type") == "text")
            stop_reason = body.get("stop_reason") if isinstance(body, dict) else None
        usage = body.get("usage") or {}
        if self.protocol == "openai_chat_completions":
            input_tokens = usage.get("prompt_tokens")
            output_tokens = usage.get("completion_tokens")
        else:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
        total_tokens = input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None
        token_usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                       "total_tokens": total_tokens, "cached_input_tokens": usage.get("cache_read_input_tokens"),
                       "reasoning_tokens": None,
                       "complete": input_tokens is not None and output_tokens is not None and total_tokens is not None}
        response_message = AIMessage(
            content=visible,
            usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens},
            response_metadata={"token_usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": total_tokens},
                               "stop_reason": stop_reason, "request_id": request_id, "model": returned_model},
        )
        parsed_tool_calls = _parse_text_tool_calls(visible)
        for parsed in parsed_tool_calls:
            self.trace.pending_tool_calls.append(parsed)
        raw_tool_call_text = [parsed["raw_text"] for parsed in parsed_tool_calls]
        self.trace.event(phase, "llm_response", call_index=call_index,
                         logical_call_index=call_index,
                         response_ref=self.trace.blob_json("llm-response", serialize_message(response_message)),
                         visible_content_ref=self.trace.blob_text("llm-visible", visible),
                         raw_tool_call_text_ref=self.trace.blob_json("raw-tool-calls", raw_tool_call_text),
                         parsed_tool_calls=parsed_tool_calls,
                         token_usage=token_usage, stop_reason=stop_reason,
                         requested_model=self.model, returned_model=returned_model,
                         request_id=request_id, protocol=self.protocol, http_attempts=attempt_count,
                         response_body_ref=self.trace.blob_text("llm-response-body", raw_body_text))
        for marker in ("INFO ENOUGH", "PROPOSE LOCATION", "PROPOSE SUGGESTION", "#TOOL_CALL"):
            if marker in visible:
                self.trace.event(phase, "marker_detected", marker=marker, call_index=call_index)
        return response_message


class TracedOfficialTool:
    def __init__(self, tool: Any, trace: OfficialTrace, output_guard: bool = False):
        self.tool = tool
        self.trace = trace
        self.output_guard = output_guard
        self.name = tool.name
        self.description = getattr(tool, "description", "")
        self.args = getattr(tool, "args", {})

    def invoke(self, arguments: dict[str, Any]) -> Any:
        started = time.monotonic()
        started_utc = _utc_now()
        raw_model_call = None
        for index, pending in enumerate(self.trace.pending_tool_calls):
            if pending.get("name") == self.name:
                raw_model_call = self.trace.pending_tool_calls.pop(index)
                break
        if raw_model_call is None:
            raw_model_call = {"name": self.name, "arguments": arguments,
                              "raw_text": None, "parse_error": None}
        try:
            result = self.tool.invoke(arguments)
        except Exception as exc:
            self.trace.event("locator", "tool_call", tool_name=self.name, arguments=arguments,
                             raw_model_call_text_ref=self.trace.blob_text("tool-model-call", raw_model_call.get("raw_text") or ""),
                             parsed_arguments=raw_model_call.get("arguments", arguments),
                             start_utc=started_utc, end_utc=_utc_now(), success=False,
                             result_ref=None, agent_return_ref=None, result_chars=0,
                             original_chars=0, returned_chars=0, original_bytes=0,
                             returned_bytes=0, original_sha256=None, returned_sha256=None,
                             exception=f"{type(exc).__name__}: {exc}", latency_ms=monotonic_ms(started),
                             shell_execution=None)
            raise
        # This is precisely the serialization used by custom_tool_node when
        # it appends the textual /\\/ Tool Result message.
        raw_text = result if isinstance(result, str) else str(result)
        if self.output_guard:
            protected = protect_tool_output(self.name, result, arguments)
            returned = protected.text
            original_chars = protected.original_chars
            returned_chars = protected.returned_chars
            truncated = protected.truncated
            agent_text = returned
        else:
            # The official custom_tool_node converts this value with str()
            # when it builds the textual /\\/ Tool Result message.  Returning
            # the raw object here preserves that public-tool behavior exactly;
            # the serialized text is used only for audit counters.
            returned = result
            original_chars = len(raw_text)
            returned_chars = len(raw_text)
            truncated = False
            agent_text = raw_text
        result_ref = self.trace.blob_text(f"tool-{self.name}-raw-return", raw_text)
        agent_return_ref = self.trace.blob_text(f"tool-{self.name}-agent-return", agent_text)
        shell_execution = None
        if self.name == "execute_shell_command_with_validation":
            return_code = re.search(r"Return code:\s*(-?\d+)", raw_text)
            cwd_match = re.search(r"Working directory:\s*(.*?)(?:\n|$)", raw_text)
            stdout_match = re.search(r"STDOUT:\n(.*?)(?=\nSTDERR:\n|\nNo output\s*$|$)", raw_text, re.DOTALL)
            stderr_match = re.search(r"STDERR:\n(.*?)(?:\nNo output\s*$|$)", raw_text, re.DOTALL)
            shell_execution = {
                "command": arguments.get("command"),
                "working_directory": arguments.get("working_directory"),
                "effective_working_directory": cwd_match.group(1).strip() if cwd_match else None,
                "exit_code": int(return_code.group(1)) if return_code else None,
                "stdout_ref": self.trace.blob_text("shell-stdout", stdout_match.group(1) if stdout_match else ""),
                "stderr_ref": self.trace.blob_text("shell-stderr", stderr_match.group(1) if stderr_match else ""),
                "validation_model": "deepseek-v3",
            }
        self.trace.event("locator", "tool_call", tool_name=self.name, arguments=arguments,
                         raw_model_call_text_ref=self.trace.blob_text("tool-model-call", raw_model_call.get("raw_text") or ""),
                         parsed_arguments=raw_model_call.get("arguments", arguments),
                         success=True, result_ref=result_ref, agent_return_ref=agent_return_ref,
                         result_chars=returned_chars, original_chars=original_chars,
                         returned_chars=returned_chars, truncated=truncated,
                         original_bytes=result_ref["bytes"], returned_bytes=agent_return_ref["bytes"],
                         original_sha256=result_ref["sha256"], returned_sha256=agent_return_ref["sha256"],
                         start_utc=started_utc, end_utc=_utc_now(),
                         shell_execution=shell_execution, latency_ms=monotonic_ms(started))
        return returned


def _official_tools(trace: OfficialTrace, output_guard: bool = False,
                    arm: str = "full14") -> list[TracedOfficialTool]:
    from tools import retriever_tools

    tools = [TracedOfficialTool(getattr(retriever_tools, name), trace, output_guard)
             for name in _official_tool_names(arm)]
    return tools


def _normalise_locations(locations: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    result = []
    for location in locations or []:
        raw_path = str(location.get("file_path", ""))
        path = Path(raw_path)
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix() if path.is_absolute() else path.as_posix()
        except ValueError:
            rel = raw_path
        result.append({"file_path": rel, "start_line": location.get("start_line"), "end_line": location.get("end_line")})
    return result


def _next_attempt(output_root: Path, instance_id: str, resume: bool) -> int | None:
    instance_root = output_root / instance_id
    attempts = sorted(int(path.name) for path in instance_root.iterdir() if path.is_dir() and path.name.isdigit()) if instance_root.exists() else []
    if not attempts:
        return 0
    for attempt in reversed(attempts):
        trajectory = instance_root / str(attempt) / "trajectory.jsonl"
        if trajectory.exists():
            try:
                last = json.loads(trajectory.read_text(encoding="utf-8").splitlines()[-1])
                if last.get("event_type") == "final":
                    return None if resume else attempt + 1
            except (ValueError, IndexError, json.JSONDecodeError):
                pass
    return max(attempts) + 1


def run_one(manifest: dict[str, Any], instance_id: str, output_root: Path, repo_cache: Path,
            source_root: Path | None, model: str, api_key: str, base_url: str,
            timeout: float, attempt: int, experiment_id: str, protocol: str,
            output_guard: bool = False, arm: str = "full14",
            request_retries: int = DEFAULT_REQUEST_RETRIES,
            retry_backoff: tuple[float, ...] = DEFAULT_RETRY_BACKOFF_SECONDS,
            workers: int = 1) -> dict[str, Any]:
    _install_python313_lib2to3_stub()
    item = next(item for item in manifest["instances"] if item["instance_id"] == instance_id)
    manager = RepositoryManager(repo_cache, source_root)
    run_dir = output_root / instance_id / str(attempt)
    trajectory_path = run_dir / "trajectory.jsonl"
    static = {
        "run_id": f"sgagent-official-{instance_id}-{attempt}-{uuid.uuid4().hex[:10]}",
        "experiment_id": experiment_id, "instance_id": instance_id,
        "arm": arm, "repeat": attempt, "sampling_seed": manifest["sampling"]["seed"],
        "sgagent_commit": UPSTREAM_COMMIT, "working_tree_diff_hash": _working_tree_hash(),
        "repo": item["repo"], "repo_commit": item["base_commit"],
        "dataset_id": manifest["dataset"]["name"], "dataset_revision": manifest["dataset"]["revision"],
        "model": model,
        "provider": ("qtapi_openai_chat_completions" if protocol == "openai_chat_completions"
                      else "anthropic_qtapi_messages"),
        "protocol": protocol, "temperature": 0.0, "tool_output_guard": output_guard,
        "budgets": {"graph_recursion_limit": 150, "http_timeout_seconds": timeout, "max_output_tokens": None},
        "retry_policy": {"max_additional_retries": request_retries,
                          "backoff_seconds": list(retry_backoff),
                          "retryable_statuses": [502, 503, 504],
                          "retryable_network_errors": ["httpx.TimeoutException", "httpx.NetworkError"]},
        "workers": workers,
        "prompt_source": "experiments.name_to_definition.full_tool_prompt + prompts.locator.py",
        "tool_prompt_mode": arm,
        "enabled_tools": list(_official_tool_names(arm)),
        "disabled_tools": sorted(N2D_TOOL_NAMES) if arm == "no_n2d" else [],
        "index_mode": "official KG in-memory build; no N2D index or modified locator tools",
    }
    trace = OfficialTrace(trajectory_path, static)
    started = time.monotonic()
    termination = "budget_exhausted"
    raw_locations: list[dict[str, Any]] = []
    graph_updates = 0
    try:
        with manager.materialize(str(item["repo"]), str(item["base_commit"])) as repo_root:
            # Configure settings before importing official modules.  This is
            # the same environment main.py expects for one pending instance.
            os.environ.update({
                "TEST_BED": str(repo_root.parent), "PROJECT_NAME": repo_root.name,
                "INSTANCE_ID": instance_id, "PROBLEM_STATEMENT": str(item["problem_statement"]),
                "DATASET_PATH": str(Path(manifest["dataset"]["lite_path"]).resolve()),
                "OPENAI_MODEL": model, "OPENAI_BASE_URL": base_url, "OPENAI_API_KEY": api_key,
            })
            from settings import settings
            settings.TEST_BED = str(repo_root.parent)
            settings.PROJECT_NAME = repo_root.name
            settings.INSTANCE_ID = instance_id
            settings.PROBLEM_STATEMENT = str(item["problem_statement"])
            settings.openai_model = model
            settings.openai_base_url = base_url
            settings.openai_api_key = api_key
            from tools import retriever_tools
            retriever_tools.set_trace_hook(trace.nested_event)
            kg_started = time.monotonic()
            trace.event("locator", "kg_build_start", root=str(repo_root))
            retriever = retriever_tools.get_retriever()
            trace.event("locator", "kg_build_end", latency_ms=monotonic_ms(kg_started),
                        class_count=len(retriever.classes), method_count=len(retriever.methods),
                        variable_count=len(retriever.variables), tag_count=len(retriever.tags))
            from prompts import fixer, locator, suggester
            official_tools = _official_tools(trace, output_guard, arm)
            tool_manifest = [{"name": tool.name, "description": tool.description, "parameters": tool.args} for tool in official_tools]
            trace.writer.static.update({"tool_manifest": tool_manifest})
            prompt_template = tool_system_template(arm)
            trace.writer.static.update({
                "prompt_templates": {
                    "tool_system": trace.blob_text("prompt-tool-system", prompt_template),
                    "locator_role": trace.blob_text("prompt-locator-role", locator),
                    "suggester_role": trace.blob_text("prompt-suggester-role", suggester),
                    "fixer_role": trace.blob_text("prompt-fixer-role", fixer),
                },
                "prompt_hashes": {
                    "tool_system": hashlib.sha256(prompt_template.encode()).hexdigest(),
                    "locator_role": hashlib.sha256(locator.encode()).hexdigest(),
                    "suggester_role": hashlib.sha256(suggester.encode()).hexdigest(),
                    "fixer_role": hashlib.sha256(fixer.encode()).hexdigest(),
                },
            })
            trace.event("locator", "run_start", index_mode="official_kg", index_file_count=None,
                        graph_recursion_limit=150, tool_manifest=tool_manifest,
                        enabled_tools=list(_official_tool_names(arm)),
                        disabled_tools=sorted(N2D_TOOL_NAMES) if arm == "no_n2d" else [])
            client = QtapiOfficialChat(model, api_key, base_url, 0.0, timeout, trace, protocol,
                                       request_retries=request_retries,
                                       retry_backoff=retry_backoff)
            llm = RunnableLambda(lambda value: client.invoke(value))
            from agent import core as agent_core
            agent_core.set_trace_hook(trace.agent_event)
            from agent.core import agent_node, custom_tool_node, create_agent
            from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
            from prompts import fixer, locator, suggester
            from workflow.graph import create_workflow
            from langchain_core.messages import HumanMessage
            locator_template = ChatPromptTemplate.from_messages([
                ("system", tool_system_template(arm) + locator),
                MessagesPlaceholder(variable_name="messages"),
            ])
            suggester_template = ChatPromptTemplate.from_messages([
                ("system", tool_system_template(arm) + suggester),
                MessagesPlaceholder(variable_name="messages"),
            ])
            fixer_template = ChatPromptTemplate.from_messages([
                ("system", tool_system_template(arm) + fixer),
                MessagesPlaceholder(variable_name="messages"),
            ])
            # create_workflow is the public graph constructor.  RunnableLambda
            # deliberately has no bind_tools method, preserving the original
            # text #TOOL_CALL protocol instead of introducing native tool use.
            workflow = create_workflow(
                llm=llm, locator_tools=official_tools, suggester_tools=official_tools,
                fixer_tools=official_tools, locator_template=locator_template,
                suggester_template=suggester_template, fixer_template=fixer_template,
                base_dir=str(repo_root.parent), project_name=repo_root.name, trace=trace,
            ).compile()
            initial_state = {
                "messages": [HumanMessage(content="Try to find and repair the bug in the project.")],
                "initial_failure": None, "location": None, "locations": None,
                "suggestion": "", "suggest_count": 0, "fix_count": 0, "patch": "",
                "ready_to_locate": False, "ready_to_fix": False, "summary": "",
                "invoker": "", "next": "Locator", "failed_location": [], "update_num": 1,
                "location_content": "", "problem_statement": str(item["problem_statement"]),
            }
            previous_nodes = None
            for update in workflow.stream(initial_state, {"recursion_limit": 150}):
                graph_updates += 1
                nodes = sorted(update.keys())
                trace.event("workflow", "graph_update", nodes=nodes)
                if previous_nodes is not None:
                    trace.event("workflow", "graph_transition", from_nodes=previous_nodes, to_nodes=nodes)
                previous_nodes = nodes
                locator_update = update.get("Locator") if isinstance(update, dict) else None
                candidate_locations = locator_update.get("locations") if isinstance(locator_update, dict) else None
                if candidate_locations:
                    raw_locations = [dict(location) for location in candidate_locations]
                    termination = "completed"
                    trace.event("locator", "locator_output", raw_locations=raw_locations,
                                ranked=True, parseable=True)
                    break
    except Exception as exc:
        if isinstance(exc, (httpx.TimeoutException, concurrent.futures.TimeoutError, TimeoutError)):
            termination = "timeout"
        elif isinstance(exc, subprocess.TimeoutExpired):
            termination = "timeout"
        elif type(exc).__name__ == "GraphRecursionError":
            termination = "budget_exhausted"
        else:
            termination = "api_error" if isinstance(exc, (httpx.HTTPError, RuntimeError)) else "runtime_error"
        trace.event("locator", "run_error", error_type=type(exc).__name__, error=str(exc),
                    traceback=traceback.format_exc(limit=8))
    finally:
        if "retriever_tools" in locals():
            retriever_tools.set_trace_hook(None)
        if "agent_core" in locals():
            agent_core.set_trace_hook(None)
        logical_requests = [event for event in trace.records
                            if event.get("event_type") in {"llm_request", "nested_llm_request"}]
        llm_events = [event for event in trace.records
                      if event.get("event_type") in {"llm_response", "nested_llm_response"}]
        locator_llm = [event for event in logical_requests if event.get("phase") == "locator"]
        summarizer_llm = [event for event in logical_requests if event.get("phase") == "summarizer"]
        nested_llm = [event for event in logical_requests if event.get("event_type") == "nested_llm_request"]
        http_attempt_events = [event for event in trace.records if event.get("event_type") == "llm_http_attempt"]
        usages = [event.get("token_usage") or {} for event in llm_events]
        token_complete = all(bool(usage.get("complete")) for usage in usages) and bool(usages)
        token_total = sum(int(usage["total_tokens"]) for usage in usages) if token_complete else None
        input_total = sum(int(usage["input_tokens"]) for usage in usages) if token_complete else None
        output_total = sum(int(usage["output_tokens"]) for usage in usages) if token_complete else None
        successful_tools = [event for event in trace.records if event.get("event_type") == "tool_call" and event.get("success")]
        failed_tools = [event for event in trace.records if event.get("event_type") == "tool_call" and not event.get("success")]
        locator_responses = [event for event in llm_events if event.get("phase") == "locator"]
        locator_tool_responses = sum(1 for event in locator_responses if event.get("parsed_tool_calls"))
        reflection_turns = max(0, len(locator_llm) - locator_tool_responses - (1 if termination == "completed" else 0))
        returned_models = sorted({str(event.get("returned_model")) for event in llm_events if event.get("returned_model")})
        request_ids = [event.get("request_id") for event in llm_events if event.get("request_id")]
        stop_reasons = {}
        for event in llm_events:
            reason = event.get("stop_reason")
            if reason:
                stop_reasons[str(reason)] = stop_reasons.get(str(reason), 0) + 1
        logical_calls_by_phase = {}
        successful_by_phase = {}
        tokens_by_phase = {}
        for event in logical_requests:
            phase = str(event.get("phase"))
            logical_calls_by_phase[phase] = logical_calls_by_phase.get(phase, 0) + 1
        for event in llm_events:
            phase = str(event.get("phase"))
            successful_by_phase[phase] = successful_by_phase.get(phase, 0) + 1
            usage = event.get("token_usage") or {}
            bucket = tokens_by_phase.setdefault(phase, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            for key in bucket:
                bucket[key] += int(usage.get(key, 0) or 0)
        summary = {
            "requested_model": model, "returned_models": returned_models,
            "request_ids": request_ids, "stop_reasons": stop_reasons,
            "logical_llm_calls": len(logical_requests),
            "http_attempts": len(http_attempt_events),
            "request_retries": sum(max(0, int(event.get("http_attempts", 1)) - 1)
                                   for event in llm_events if event.get("event_type") == "llm_response"),
            "successful_llm_responses": len(llm_events),
            "failed_llm_calls": sum(1 for event in trace.records
                                     if event.get("event_type") in {"llm_error", "nested_llm_error"}),
            "locator_llm_calls": len(locator_llm), "tool_calls": len(successful_tools),
            "failed_tool_calls": len(failed_tools), "reflection_turns": reflection_turns,
            "summarizer_llm_calls": len(summarizer_llm),
            "nested_llm_calls": len(nested_llm),
            "total_llm_calls": len(logical_requests),
            "logical_calls_by_phase": logical_calls_by_phase,
            "successful_responses_by_phase": successful_by_phase,
            "tokens_by_phase": tokens_by_phase,
            "tool_result_chars": sum(int(event.get("returned_chars", event.get("result_chars", 0))) for event in successful_tools),
            "tool_original_chars": sum(int(event.get("original_chars", event.get("result_chars", 0))) for event in successful_tools),
            "tool_returned_chars": sum(int(event.get("returned_chars", event.get("result_chars", 0))) for event in successful_tools),
            "tool_original_bytes": sum(int(event.get("original_bytes", 0) or 0) for event in successful_tools),
            "tool_returned_bytes": sum(int(event.get("returned_bytes", 0) or 0) for event in successful_tools),
            "truncated_tool_calls": sum(bool(event.get("truncated")) for event in successful_tools),
            "input_tokens": input_total, "output_tokens": output_total, "total_tokens": token_total,
            "token_usage_incomplete": not token_complete,
            "wall_clock_ms": monotonic_ms(started), "graph_updates": graph_updates,
            "termination_reason": termination, "raw_locations": raw_locations,
        }
        normalized = _normalise_locations(raw_locations, repo_root if "repo_root" in locals() else Path("/nonexistent"))
        summary["ranked_locations"] = normalized
        trace.event("locator", "final", ranked_locations=normalized, raw_locations=raw_locations,
                    termination_reason=termination, aggregate_counters=summary)
        trace.close()
        trajectory_path.with_name("summary.json").write_text(
            json.dumps({"schema_version": SCHEMA_VERSION, **summary, "run_id": static["run_id"],
                        "instance_id": instance_id, "model": model, "provider": static["provider"],
                        "experiment_id": experiment_id},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    return {**summary, "run_id": static["run_id"], "instance_id": instance_id,
            "trajectory_path": str(trajectory_path), "model": model,
            "experiment_id": experiment_id}


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--experiment-id", default="sgagent_official_locator_full14_reproduction")
    parser.add_argument("--output-root", default="experiments/name_to_definition/runs/official_locator_reproduction")
    parser.add_argument("--repo-cache", default="experiments/name_to_definition/repo_cache")
    parser.add_argument("--source-root")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-5")
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "https://cdn.qtapi.net")
    parser.add_argument("--protocol", choices=("openai_chat_completions", "anthropic_messages"),
                        default="anthropic_messages")
    parser.add_argument("--arm", choices=OFFICIAL_ARM_NAMES, default="full14")
    parser.add_argument("--enable-tool-output-guard", action="store_true",
                        help="Diagnostic-only 32,000-character experiment-layer guard.")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--request-retries", type=int, default=DEFAULT_REQUEST_RETRIES)
    parser.add_argument("--retry-backoff", default=",".join(str(value) for value in DEFAULT_RETRY_BACKOFF_SECONDS),
                        help="Comma-separated fixed backoff seconds for request-level retries.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--instances", help="Comma-separated instance IDs to run; useful for immutable failed-sample recovery.")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--child-instance")
    parser.add_argument("--attempt", type=int, default=0)
    args = parser.parse_args()
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY") or ""
    if not api_key:
        raise SystemExit("missing secure qtapi API credential in environment")
    manifest = _load_manifest(Path(args.manifest))
    retry_backoff = tuple(float(value) for value in args.retry_backoff.split(",") if value.strip())
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if args.child_instance:
        result = run_one(manifest, args.child_instance, output_root, Path(args.repo_cache),
                         Path(args.source_root) if args.source_root else None,
                         args.model, api_key, args.base_url, args.timeout, args.attempt,
                         args.experiment_id, args.protocol, args.enable_tool_output_guard,
                         args.arm, args.request_retries, retry_backoff, args.workers)
        print(json.dumps(result, ensure_ascii=False, default=str))
        return
    rows = manifest["instances"][:args.limit] if args.limit else manifest["instances"]
    if args.instances:
        selected = {value.strip() for value in args.instances.split(",") if value.strip()}
        rows = [item for item in rows if item["instance_id"] in selected]

    def run_child(item: dict[str, Any]) -> dict[str, Any]:
        instance_id = item["instance_id"]
        instance_root = output_root / instance_id
        attempts = sorted(int(path.name) for path in instance_root.iterdir() if path.is_dir() and path.name.isdigit()) if instance_root.exists() else []
        attempt = None
        if attempts:
            for candidate in reversed(attempts):
                trajectory = instance_root / str(candidate) / "trajectory.jsonl"
                if trajectory.exists():
                    try:
                        last = json.loads(trajectory.read_text(encoding="utf-8").splitlines()[-1])
                        if last.get("event_type") == "final":
                            # Resume only skips a genuinely completed sample;
                            # provider/runtime failures get a fresh attempt
                            # while the failed trajectory remains immutable.
                            attempt = (None if args.resume and last.get("termination_reason") == "completed"
                                       else candidate + 1)
                            break
                    except (ValueError, IndexError, json.JSONDecodeError):
                        pass
            if attempt is None and not args.resume:
                attempt = max(attempts) + 1
        else:
            attempt = 0
        if attempt is None:
            return {"instance_id": instance_id, "skipped": True}
        command = [sys.executable, "-m", "experiments.name_to_definition.official_locator",
                   "--manifest", args.manifest, "--output-root", str(output_root),
                   "--experiment-id", args.experiment_id,
                   "--repo-cache", args.repo_cache, "--model", args.model, "--base-url", args.base_url,
                   "--protocol", args.protocol,
                   "--arm", args.arm, "--timeout", str(args.timeout),
                   "--request-retries", str(args.request_retries),
                   "--retry-backoff", args.retry_backoff,
                   "--child-instance", instance_id, "--attempt", str(attempt),
                   "--workers", str(args.workers)]
        if args.enable_tool_output_guard:
            command.append("--enable-tool-output-guard")
        if args.source_root:
            command.extend(["--source-root", args.source_root])
        started = time.monotonic()
        completed = subprocess.run(command, env=os.environ.copy(), capture_output=True, text=True)
        if completed.returncode == 0:
            try:
                return json.loads(completed.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError, json.JSONDecodeError):
                pass
        return {"instance_id": instance_id, "attempt": attempt, "termination_reason": "worker_error",
                "returncode": completed.returncode, "wall_clock_ms": round((time.monotonic() - started) * 1000, 3),
                "worker_stderr_tail": completed.stderr[-2000:]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        results = list(executor.map(run_child, rows))
    (output_root / "run_summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"instances": len(rows), "results": len(results), "output_root": str(output_root)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
