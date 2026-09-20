"""A deterministic, repository-local Python definition index.

The phase-one N2D tools intentionally expose only metadata.  Code bodies and
relationships remain available through the common tools, so the treatment does
not bundle extra context into a name lookup.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".tox", ".venv", "venv", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", "build", "dist",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or path.stem


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(node.args).replace("\n", " ")
    except Exception:
        args = ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args})"


def _base_record(kind: str, name: str, fqn: str, path: Path,
                 root: Path, start: int, end: int, signature: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "candidate_id": f"{path.relative_to(root).as_posix()}:{fqn}",
        "kind": kind,
        "file_path": path.relative_to(root).as_posix(),
        "full_qualified_name": fqn,
        "start_line": int(start),
        "end_line": int(end or start),
    }
    if signature is not None:
        record["signature"] = signature
    return record


class _DefinitionVisitor(ast.NodeVisitor):
    def __init__(self, root: Path, path: Path, module: str, text: str):
        self.root = root
        self.path = path
        self.module = module
        self.text = text
        self.methods: list[dict[str, Any]] = []
        self.variables: list[dict[str, Any]] = []
        self._scope: list[str] = []
        self._function_depth = 0

    def _add_assign(self, node: ast.Assign | ast.AnnAssign) -> None:
        # Index module/class attributes and assignments in functions.  The
        # latter makes the variable index useful for identifiers mentioned in
        # issue reports while retaining stable source locations.
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, (ast.Name, ast.Tuple, ast.List))]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        for target in targets:
            names = [target.id] if isinstance(target, ast.Name) else [
                elt.id for elt in ast.walk(target) if isinstance(elt, ast.Name)
            ]
            for name in names:
                fqn = ".".join([self.module, *self._scope, name])
                self.variables.append(_base_record(
                    "variable", name, fqn, self.path, self.root,
                    getattr(node, "lineno", 1), getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                ))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self._scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        fqn = ".".join([self.module, *self._scope, node.name])
        self.methods.append(_base_record(
            "method", node.name, fqn, self.path, self.root,
            node.lineno, getattr(node, "end_lineno", node.lineno), _signature(node),
        ))
        # Nested functions are definitions too, but do not duplicate the
        # function node itself when walking its body.
        self._scope.append(node.name)
        self._function_depth += 1
        for child in node.body:
            self.visit(child)
        self._function_depth -= 1
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._add_assign(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._add_assign(node)
        self.generic_visit(node)


class RepositoryIndex:
    """AST index with stable ordering and a content hash."""

    def __init__(self, root: str | Path, only_files: set[str] | None = None):
        self.root = Path(root).resolve()
        self.only_files = {str(path).replace("\\", "/") for path in only_files} if only_files is not None else None
        self.methods: list[dict[str, Any]] = []
        self.variables: list[dict[str, Any]] = []
        self.files: list[str] = []
        self.file_text: dict[str, str] = {}
        self._methods_by_name: dict[str, list[dict[str, Any]]] = {}
        self._variables_by_name: dict[str, list[dict[str, Any]]] = {}
        self.index_hash = ""
        self.build()

    def _python_files(self) -> Iterable[Path]:
        for path in sorted(self.root.rglob("*.py")):
            relative = path.relative_to(self.root)
            if self.only_files is not None and relative.as_posix() not in self.only_files:
                continue
            if any(part in EXCLUDED_DIRS for part in relative.parts):
                continue
            yield path

    def build(self) -> None:
        digest = hashlib.sha256()
        for path in self._python_files():
            rel = path.relative_to(self.root).as_posix()
            text = _read_text(path)
            self.files.append(rel)
            self.file_text[rel] = text
            digest.update(rel.encode())
            digest.update(b"\0")
            digest.update(text.encode("utf-8", errors="replace"))
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(text, filename=rel)
            except SyntaxError:
                continue
            visitor = _DefinitionVisitor(self.root, path, _module_name(self.root, path), text)
            visitor.visit(tree)
            self.methods.extend(visitor.methods)
            self.variables.extend(visitor.variables)
        self.methods.sort(key=lambda x: (x["file_path"], x["start_line"], x["end_line"], x["full_qualified_name"]))
        self.variables.sort(key=lambda x: (x["file_path"], x["start_line"], x["end_line"], x["full_qualified_name"]))
        for candidate in self.methods:
            self._methods_by_name.setdefault(candidate["full_qualified_name"].rsplit(".", 1)[-1], []).append(candidate)
        for candidate in self.variables:
            self._variables_by_name.setdefault(candidate["full_qualified_name"].rsplit(".", 1)[-1], []).append(candidate)
        self.index_hash = digest.hexdigest()

    def definitions(self, kind: str, query: str, match_mode: str = "exact") -> list[dict[str, Any]]:
        pool = self.methods if kind == "method" else self.variables
        if match_mode == "exact":
            by_name = self._methods_by_name if kind == "method" else self._variables_by_name
            result = list(by_name.get(query, []))
        elif match_mode == "substring":
            result = [c for c in pool if query in c["full_qualified_name"].rsplit(".", 1)[-1]]
        else:
            raise ValueError(f"unsupported match_mode: {match_mode}")
        return sorted(result, key=lambda x: (x["file_path"], x["start_line"], x["end_line"], x["full_qualified_name"]))

    def candidate_page(self, kind: str, query: str, top_k: int = 20,
                       cursor: int = 0, match_mode: str = "exact") -> dict[str, Any]:
        if top_k < 1 or top_k > 100:
            raise ValueError("top_k must be between 1 and 100")
        if cursor < 0:
            raise ValueError("cursor must be non-negative")
        all_candidates = self.definitions(kind, query, match_mode)
        page = all_candidates[cursor:cursor + top_k]
        next_cursor = cursor + top_k if cursor + top_k < len(all_candidates) else None
        return {
            "query": query,
            "match_mode": match_mode,
            "total_candidates": len(all_candidates),
            "candidates": page,
            "next_cursor": next_cursor,
        }

    def metadata_for_method(self, file_path: str, fqn: str) -> list[dict[str, Any]]:
        return [c for c in self.methods if c["file_path"] == file_path and c["full_qualified_name"] == fqn]

    def metadata_for_file(self, file_path: str) -> list[dict[str, Any]]:
        return [c for c in self.methods if c["file_path"] == file_path]

    def absolute(self, file_path: str) -> Path:
        candidate = Path(file_path)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.root / candidate).resolve()

    def to_json(self) -> str:
        return json.dumps({"root": str(self.root), "index_hash": self.index_hash,
                           "methods": self.methods, "variables": self.variables}, sort_keys=True)
