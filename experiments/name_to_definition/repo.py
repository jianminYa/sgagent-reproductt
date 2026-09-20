"""Safe materialization of dataset repository commits outside the worktree."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import hashlib
import re
import io
import tarfile
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Iterator


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd) if cwd else None, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


class RepositoryManager:
    def __init__(self, cache_root: str | Path, source_root: str | Path | None = None):
        self.cache_root = Path(cache_root).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.source_root = Path(source_root).resolve() if source_root else None
        self._repo_locks: dict[str, threading.Lock] = {}
        self._repo_locks_guard = threading.Lock()

    def _repo_lock(self, repo: str) -> threading.Lock:
        with self._repo_locks_guard:
            return self._repo_locks.setdefault(repo, threading.Lock())

    def _local_repo(self, repo: str) -> Path | None:
        slug = repo.replace("/", "__")
        candidates = []
        if self.source_root:
            candidates.extend([self.source_root / slug, self.source_root / repo.split("/", 1)[-1]])
        candidates.append(Path("/home/jql/.orcar") / slug)
        for path in candidates:
            if (path / ".git").exists():
                return path
        return None

    def _cache_repo(self, repo: str) -> Path:
        path = self.cache_root / repo.replace("/", "__")
        if not (path / ".git").exists():
            _run(["git", "clone", "--filter=blob:none", "--no-checkout", f"https://github.com/{repo}.git", str(path)])
        return path

    def _repo_for_commit(self, repo: str, commit: str) -> Path:
        with self._repo_lock(repo):
            local = self._local_repo(repo)
            path = local or self._cache_repo(repo)
            try:
                _run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=path)
            except subprocess.CalledProcessError:
                _run(["git", "fetch", "--filter=blob:none", "origin", commit], cwd=path)
            return path

    def probe_definition_names(self, repo: str, commit: str, tokens: list[str]) -> tuple[dict[str, int], str]:
        """Count exact method/assignment definitions without materializing a tree.

        This is the sampler's pre-treatment probe. The runner independently
        builds the full AST index from the same commit before exposing tools.
        """
        source = self._repo_for_commit(repo, commit)
        try:
            tree_hash = _run(["git", "rev-parse", f"{commit}^{{tree}}"], cwd=source).stdout.strip()
        except subprocess.CalledProcessError:
            tree_hash = hashlib.sha256(f"{repo}@{commit}".encode()).hexdigest()
        found: set[tuple[str, str, str, str]] = set()
        safe_tokens = [t for t in tokens if re.fullmatch(r"[_A-Za-z][_A-Za-z0-9]*", t)]
        if not safe_tokens:
            return {}, tree_hash
        name_group = "(" + "|".join(re.escape(t) for t in safe_tokens) + ")"
        method_rx = re.compile(rf"^\s*(?:async\s+)?def\s+{name_group}\s*\(")
        variable_rx = re.compile(rf"^\s*{name_group}\s*(?:=|:.*=)")
        # Streaming the commit archive avoids one git-grep process per token
        # and works efficiently with blob-filtered clones.
        archive = subprocess.run(["git", "archive", commit], cwd=str(source), stdout=subprocess.PIPE, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".py"):
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                for line_number, raw in enumerate(handle.read().decode("utf-8", errors="replace").splitlines(), 1):
                    method_match = method_rx.search(raw)
                    variable_match = variable_rx.search(raw)
                    if method_match:
                        found.add(("method", method_match.group(1), member.name, str(line_number)))
                    if variable_match:
                        found.add(("variable", variable_match.group(1), member.name, str(line_number)))
        counts: dict[str, int] = {}
        for _, name, _, _ in found:
            counts[name] = counts.get(name, 0) + 1
        return counts, tree_hash

    @contextmanager
    def materialize(self, repo: str, commit: str) -> Iterator[Path]:
        source = self._repo_for_commit(repo, commit)
        temp = Path(tempfile.mkdtemp(prefix="sgagent-n2d-"))
        try:
            archive = subprocess.run(["git", "archive", commit], cwd=str(source), stdout=subprocess.PIPE, check=True).stdout
            import tarfile, io
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
                tar.extractall(temp)
            yield temp
        finally:
            shutil.rmtree(temp, ignore_errors=True)
