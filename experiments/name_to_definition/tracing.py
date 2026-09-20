"""Append-only trajectory writer with explicit missing-token semantics."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION


SECRET_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,})")


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return SECRET_RE.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items() if str(k).lower() not in {"authorization", "api_key", "token"}}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(redact(value), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def serialize_message(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return redact(message)
    result: dict[str, Any] = {"type": getattr(message, "type", type(message).__name__)}
    for key in ("role", "name", "content", "tool_call_id", "tool_calls", "additional_kwargs"):
        if hasattr(message, key):
            result[key] = redact(getattr(message, key))
    return result


def extract_token_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage_metadata", None) or {}
    metadata = getattr(response, "response_metadata", None) or {}
    legacy = metadata.get("token_usage") or metadata.get("usage") or {}
    def pick(*keys: str) -> int | None:
        for source in (usage, legacy, metadata):
            for key in keys:
                value = source.get(key) if isinstance(source, dict) else None
                if isinstance(value, (int, float)):
                    return int(value)
        return None
    input_tokens = pick("input_tokens", "prompt_tokens")
    output_tokens = pick("output_tokens", "completion_tokens")
    total = pick("total_tokens")
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": total,
        "cached_input_tokens": pick("cache_read_input_tokens", "cached_tokens"),
        "reasoning_tokens": pick("reasoning_tokens"),
        "complete": input_tokens is not None and output_tokens is not None and total is not None,
    }


class TrajectoryWriter:
    def __init__(self, path: str | Path, static: dict[str, Any]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.static = redact(static)
        self.seq = 0
        self._fh = self.path.open("a", encoding="utf-8")

    def event(self, phase: str, event_type: str, **payload: Any) -> dict[str, Any]:
        self.seq += 1
        record = {
            **self.static, "schema_version": SCHEMA_VERSION, "seq": self.seq,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "phase": phase, "event_type": event_type,
            **redact(payload),
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        self._fh.flush()
        return record

    def close(self) -> None:
        self._fh.close()


class SidecarStore:
    """Content-addressed, append-only storage for complete trace payloads.

    Trace records contain only a relative reference and integrity metadata for
    large values.  Values are redacted before they leave the process, so a
    sidecar cannot become an accidental credential dump.
    """

    def __init__(self, trajectory_path: str | Path):
        self.trajectory_path = Path(trajectory_path)
        self.root = self.trajectory_path.parent / "blobs"
        self.root.mkdir(parents=True, exist_ok=True)

    def put_text(self, label: str, value: Any) -> dict[str, Any]:
        text = redact(value) if isinstance(value, str) else redact(str(value))
        data = text.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("._") or "blob"
        path = self.root / f"{safe_label}-{digest[:16]}-{uuid.uuid4().hex[:8]}.txt"
        path.write_bytes(data)
        return {
            "path": path.relative_to(self.trajectory_path.parent).as_posix(),
            "sha256": digest,
            "chars": len(text),
            "bytes": len(data),
            "encoding": "utf-8",
            "redacted": True,
        }

    def put_json(self, label: str, value: Any) -> dict[str, Any]:
        text = json.dumps(redact(value), ensure_ascii=False, sort_keys=True, default=str)
        data = text.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("._") or "blob"
        path = self.root / f"{safe_label}-{digest[:16]}-{uuid.uuid4().hex[:8]}.json"
        path.write_bytes(data)
        return {
            "path": path.relative_to(self.trajectory_path.parent).as_posix(),
            "sha256": digest,
            "chars": len(text),
            "bytes": len(data),
            "encoding": "utf-8",
            "redacted": True,
        }


def monotonic_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 3)
