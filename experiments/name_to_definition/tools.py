"""The phase-one tool registry.  Both arms are assembled from this module."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .index import RepositoryIndex


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _clip(text: str, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated; original_chars={len(text)}]"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def openai_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters,
        }}


COMMON_TOOL_NAMES = (
    "explore_directory", "search_code_with_context", "find_files_containing",
    "analyze_file_structure", "extract_complete_method", "get_code_relationships",
    "find_variable_usage", "show_file_imports", "read_file_lines",
)
N2D_TOOL_NAMES = ("find_methods_by_name", "find_all_variables_named")


def _string_param(name: str, description: str) -> dict[str, Any]:
    return {"type": "object", "properties": {name: {"type": "string", "description": description}}, "required": [name], "additionalProperties": False}


def _registry(index: RepositoryIndex) -> dict[str, ToolSpec]:
    root = index.root

    def explore_directory(dir_path: str, prefix: str = "") -> str:
        path = index.absolute(dir_path)
        if not path.is_dir():
            return f'Directory "{dir_path}" does not exist.'
        return "Contents of " + str(path) + ":\n" + "\n".join(
            f"{p.name}{'/' if p.is_dir() else ''}" for p in sorted(path.iterdir()) if p.name != ".git"
        )

    def read_file_lines(file_path: str, start_line: int, end_line: int) -> str:
        path = index.absolute(file_path)
        if not path.is_file():
            return f"File: {file_path}\nError: file does not exist"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line)); end = min(len(lines), max(start, int(end_line)), start + 49)
        body = "\n".join(f"{i:4d}: {lines[i-1]}" for i in range(start, end + 1))
        return f"File: {path}\nTotal lines: {len(lines)}\nShowing lines {start}-{end}:\n\n{body}"

    def search_code_with_context(keyword: str, search_path: str) -> str:
        base = index.absolute(search_path)
        paths = [base] if base.is_file() else sorted(base.rglob("*.py")) if base.is_dir() else []
        results: list[str] = []
        for path in paths:
            if path.suffix != ".py" or any(p in {".git", "__pycache__"} for p in path.parts):
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines):
                if keyword in line:
                    lo, hi = max(0, i - 3), min(len(lines), i + 4)
                    results.append(f"File: {path}\nLines {lo+1}-{hi}:\n" + "\n".join(f"{j+1:4d}: {lines[j]}" for j in range(lo, hi)))
                    if len(results) >= 15:
                        return _clip("Search results:\n\n" + "\n\n".join(results))
        return _clip("Search results:\n\n" + "\n\n".join(results)) if results else f"No matches found for '{keyword}'"

    def find_files_containing(keyword: str) -> list[str]:
        paths = []
        for rel, text in index.file_text.items():
            if keyword.lower() in text.lower() or keyword.lower() in Path(rel).name.lower():
                paths.append(rel)
        return sorted(paths)

    def analyze_file_structure(file: str) -> str:
        path = Path(file)
        rel = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        methods = index.metadata_for_file(rel)
        return _json({"file_path": rel, "methods": methods})

    def extract_complete_method(file: str, full_qualified_name: str) -> str:
        path = index.absolute(file)
        rel = path.relative_to(root).as_posix()
        candidates = index.metadata_for_method(rel, full_qualified_name)
        if not candidates:
            return _json({"error": "method_not_found", "file_path": rel, "full_qualified_name": full_qualified_name})
        c = candidates[0]
        lines = index.file_text[rel].splitlines()
        body = "\n".join(f"{i:4d}: {lines[i-1]}" for i in range(c["start_line"], min(c["end_line"], len(lines)) + 1))
        return _clip(_json({"file_path": rel, "full_qualified_name": full_qualified_name,
                            "start_line": c["start_line"], "end_line": c["end_line"], "content": body,
                            "relationships": {"CALLS": [], "REFERENCES": []}}))

    def get_code_relationships(file: str, full_qualified_name: str) -> dict[str, Any]:
        return {"file_path": str(file), "full_qualified_name": full_qualified_name,
                "BELONGS_TO": [], "CALLS": [], "HAS_METHOD": [], "HAS_VARIABLE": [],
                "INHERITS": [], "REFERENCES": []}

    def find_variable_usage(file: str, variable_name: str) -> str:
        path = index.absolute(file)
        if not path.is_file():
            return f"File not found: {file}"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        rx = re.compile(rf"\b{re.escape(variable_name)}\b")
        hits = [f"{i+1:4d}: {line}" for i, line in enumerate(lines) if rx.search(line)]
        return "\n".join(hits[:100]) or f"No usage found for {variable_name}"

    def show_file_imports(python_file_path: str) -> list[str]:
        path = index.absolute(python_file_path)
        if not path.is_file():
            return []
        return [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if re.match(r"^\s*(?:from|import)\s+", line)]

    def find_methods_by_name(name: str, top_k: int = 20, cursor: int = 0, match_mode: str = "exact") -> dict[str, Any]:
        return index.candidate_page("method", name, top_k, cursor, match_mode)

    def find_all_variables_named(variable_name: str, top_k: int = 20, cursor: int = 0, match_mode: str = "exact") -> dict[str, Any]:
        return index.candidate_page("variable", variable_name, top_k, cursor, match_mode)

    specs = {
        "explore_directory": ToolSpec("explore_directory", "List one directory level.", {"type": "object", "properties": {"dir_path": {"type": "string"}, "prefix": {"type": "string"}}, "required": ["dir_path"], "additionalProperties": False}, explore_directory),
        "search_code_with_context": ToolSpec("search_code_with_context", "Search Python source and return compact surrounding context.", {"type": "object", "properties": {"keyword": {"type": "string"}, "search_path": {"type": "string"}}, "required": ["keyword", "search_path"], "additionalProperties": False}, search_code_with_context),
        "find_files_containing": ToolSpec("find_files_containing", "Find repository-relative Python files containing a keyword.", _string_param("keyword", "Keyword"), find_files_containing),
        "analyze_file_structure": ToolSpec("analyze_file_structure", "List classes and methods metadata for one Python file.", _string_param("file", "Repository-relative or absolute path"), analyze_file_structure),
        "extract_complete_method": ToolSpec("extract_complete_method", "Read one complete method body. This is the shared content retrieval tool.", {"type": "object", "properties": {"file": {"type": "string"}, "full_qualified_name": {"type": "string"}}, "required": ["file", "full_qualified_name"], "additionalProperties": False}, extract_complete_method),
        "get_code_relationships": ToolSpec("get_code_relationships", "Return relationships for a known entity.", {"type": "object", "properties": {"file": {"type": "string"}, "full_qualified_name": {"type": "string"}}, "required": ["file", "full_qualified_name"], "additionalProperties": False}, get_code_relationships),
        "find_variable_usage": ToolSpec("find_variable_usage", "Find usages of a variable in one file.", {"type": "object", "properties": {"file": {"type": "string"}, "variable_name": {"type": "string"}}, "required": ["file", "variable_name"], "additionalProperties": False}, find_variable_usage),
        "show_file_imports": ToolSpec("show_file_imports", "List import statements in one Python file.", _string_param("python_file_path", "Repository-relative or absolute path"), show_file_imports),
        "read_file_lines": ToolSpec("read_file_lines", "Read at most 50 numbered lines from a source file.", {"type": "object", "properties": {"file_path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["file_path", "start_line", "end_line"], "additionalProperties": False}, read_file_lines),
        "find_methods_by_name": ToolSpec("find_methods_by_name", "Pure name-to-definition lookup: compact method candidate metadata only; no body or relationships. Exact matching is default; explicitly set match_mode=substring for fallback.", {"type": "object", "properties": {"name": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "integer", "minimum": 0}, "match_mode": {"type": "string", "enum": ["exact", "substring"]}}, "required": ["name"], "additionalProperties": False}, find_methods_by_name),
        "find_all_variables_named": ToolSpec("find_all_variables_named", "Pure name-to-definition lookup: compact variable candidate metadata only; no content or relationships. Exact matching is default; explicitly set match_mode=substring for fallback.", {"type": "object", "properties": {"variable_name": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "integer", "minimum": 0}, "match_mode": {"type": "string", "enum": ["exact", "substring"]}}, "required": ["variable_name"], "additionalProperties": False}, find_all_variables_named),
    }
    return specs


def tool_registry(index: RepositoryIndex, arm: str) -> list[ToolSpec]:
    if arm not in {"baseline", "n2d"}:
        raise ValueError(f"unknown arm: {arm}")
    specs = _registry(index)
    names = list(COMMON_TOOL_NAMES) + (list(N2D_TOOL_NAMES) if arm == "n2d" else [])
    return [specs[name] for name in names]


def manifest_for_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [tool.openai_schema() for tool in tools]
