"""Deterministic, arm-shared protection for oversized tool results.

The guard sits at the experiment tool boundary. It does not alter the
underlying retriever or candidate ordering; it only limits the text sent back
to the model and records the before/after sizes for auditing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


DEFAULT_MAX_CHARS = 32_000
_LOCATION_KEYS = {
    "absolute_path", "file", "file_path", "full_qualified_name", "name",
    "start_line", "end_line", "line", "start", "end",
}
_RELATIONSHIP_KEYS = {
    "relationships", "analysis", "calls", "belongs_to", "has_method",
    "has_variable", "inherits", "references", "tested_by", "tests",
    "CALLS", "BELONGS_TO", "HAS_METHOD", "HAS_VARIABLE", "INHERITS", "REFERENCES",
}


@dataclass(frozen=True)
class ProtectedToolOutput:
    text: str
    original_chars: int
    returned_chars: int
    truncated: bool


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 80:
        return value[:limit]
    head = max(1, int(limit * 0.78))
    tail = max(1, limit - head - 60)
    return f"{value[:head]}\n... [content clipped] ...\n{value[-tail:]}"


def _relationship_metadata(value: Any, depth: int = 0) -> Any:
    """Drop relationship bodies while preserving identity and line metadata."""
    if depth > 4:
        return "[relationship depth clipped]"
    if isinstance(value, dict):
        kept = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _LOCATION_KEYS or key_text in {"type", "kind", "relation"}:
                kept[key_text] = item if not isinstance(item, (dict, list)) else _relationship_metadata(item, depth + 1)
            elif isinstance(item, (dict, list)):
                kept[key_text] = _relationship_metadata(item, depth + 1)
        return kept
    if isinstance(value, list):
        items = [_relationship_metadata(item, depth + 1) for item in value[:40]]
        if len(value) > 40:
            items.append(f"[{len(value) - 40} relationship entries omitted]")
        return items
    return value


def _compact(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "[nested output clipped]"
    if isinstance(value, str):
        return _clip(value, 12_000)
    if isinstance(value, dict):
        result = {}
        # Identity and location fields are placed first so a final hard fit
        # still keeps them visible.
        keys = sorted(value, key=lambda key: (str(key) not in _LOCATION_KEYS, str(key)))
        for key in keys:
            key_text = str(key)
            item = value[key]
            if key_text in _RELATIONSHIP_KEYS:
                result[key_text] = _relationship_metadata(item)
            elif key_text == "content" and isinstance(item, str):
                result[key_text] = _clip(item, 12_000)
            elif isinstance(item, (dict, list)):
                result[key_text] = _compact(item, depth + 1)
            elif isinstance(item, str):
                result[key_text] = _clip(item, 3_000)
            else:
                result[key_text] = item
        return result
    if isinstance(value, list):
        items = [_compact(item, depth + 1) for item in value[:40]]
        if len(value) > 40:
            items.append(f"[{len(value) - 40} result entries omitted]")
        return items
    return value


def _location_summary(value: Any, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if len(found) >= 40:
            return
        if isinstance(item, dict):
            location = {str(key): item[key] for key in item if str(key) in _LOCATION_KEYS}
            if any(key in location for key in ("file_path", "absolute_path", "full_qualified_name", "start_line", "end_line")):
                found.append(location)
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    argument_location = {str(key): arguments[key] for key in arguments if str(key) in _LOCATION_KEYS}
    if argument_location:
        found.append(argument_location)
    visit(value)
    unique: list[dict[str, Any]] = []
    seen = set()
    for item in found:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique[:40]


def protect_tool_output(tool_name: str, result: Any, arguments: dict[str, Any] | None = None,
                        max_chars: int = DEFAULT_MAX_CHARS) -> ProtectedToolOutput:
    arguments = arguments or {}
    original = _text(result)
    if len(original) <= max_chars:
        return ProtectedToolOutput(original, len(original), len(original), False)

    compact = _compact(result)
    compact_text = _text(compact)
    locations = _location_summary(result, arguments)
    prefix = _text({
        "_output_guard": {
            "tool": tool_name,
            "original_chars": len(original),
            "max_chars": max_chars,
            "truncated": True,
            "note": "relationship bodies were reduced; use preserved content/path/name/line fields for follow-up",
        },
        "location_summary": locations,
    })
    available = max_chars - len(prefix) - 1
    if available < 200:
        returned = _clip(prefix, max_chars)
    elif len(compact_text) <= available:
        returned = prefix + "\n" + compact_text
    else:
        returned = prefix + "\n" + _clip(compact_text, available)
    return ProtectedToolOutput(returned, len(original), len(returned), True)
