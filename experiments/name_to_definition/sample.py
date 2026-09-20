"""Freeze a deterministic pilot manifest from the Lite/Verified intersection."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .index import RepositoryIndex
from .repo import RepositoryManager


IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9_])[_A-Za-z][_A-Za-z0-9]{2,}(?![A-Za-z0-9_])")
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "does", "not", "when", "into",
    "should", "would", "could", "please", "have", "has", "are", "was", "were", "class", "function",
    "issue", "problem", "support", "error", "none", "true", "false", "self", "python", "return",
}


def identifier_like_tokens(issue: str) -> list[str]:
    """Extract pre-treatment code identifiers without treating prose as names."""
    tokens: set[str] = set()
    # Issue markup is the strongest signal for a code identifier.
    for marked in re.findall(r"`([^`]+)`", issue):
        for token in re.findall(r"(?<![A-Za-z0-9_])[_A-Za-z][_A-Za-z0-9]*(?![A-Za-z0-9_])", marked):
            if token.lower() not in STOPWORDS:
                tokens.add(token)
    # Include identifiers in fenced Python examples, but not surrounding prose.
    for block in re.findall(r"```(?:python|py)?\s*(.*?)```", issue, flags=re.IGNORECASE | re.DOTALL):
        for token in IDENTIFIER_RE.findall(block):
            if token.lower() not in STOPWORDS:
                tokens.add(token)
    if not tokens:
        # For unformatted reports require a code-shaped identifier (underscore,
        # dunder or CamelCase) to avoid common English words becoming eligible.
        for token in IDENTIFIER_RE.findall(issue):
            if token.lower() not in STOPWORDS and ("_" in token or any(c.isupper() for c in token[1:])):
                tokens.add(token)
    return sorted(tokens)


def _index_for_row(row: dict[str, Any], manager: RepositoryManager | None) -> tuple[RepositoryIndex | None, str | None]:
    if manager is None:
        return None, None
    try:
        with manager.materialize(str(row["repo"]), str(row["base_commit"])) as root:
            index = RepositoryIndex(root)
            # Keep a durable lightweight copy for this sampling process only;
            # the manifest stores the hash and eligibility, not source code.
            return index, root.as_posix()
    except Exception:
        return None, None


def _eligibility(issue: str, index: RepositoryIndex | None) -> tuple[bool, list[str], int, str]:
    tokens = identifier_like_tokens(issue)
    if index is None:
        return False, tokens, 0, "unknown_no_snapshot"
    candidates = []
    for token in tokens:
        candidates.extend(index.definitions("method", token, "exact"))
        candidates.extend(index.definitions("variable", token, "exact"))
    candidate_count = len(candidates)
    bucket = "non_eligible" if candidate_count == 0 else "1" if candidate_count == 1 else "2-5" if candidate_count <= 5 else ">5"
    return candidate_count > 0, tokens, candidate_count, bucket


def build_manifest(seed: int, size: int, lite_path: str | Path, verified_path: str | Path,
                   repo_cache: str | Path | None = None, source_root: str | Path | None = None) -> dict[str, Any]:
    lite = pd.read_parquet(lite_path)
    verified = pd.read_parquet(verified_path)
    intersection = sorted(set(lite["instance_id"]) & set(verified["instance_id"]))
    rows = verified[verified["instance_id"].isin(intersection)].copy()
    rows = rows.sort_values(["instance_id", "repo"]).drop_duplicates("instance_id")
    # First select a seeded, repository-balanced sample. Eligibility is then
    # computed only for selected rows from the corresponding base commit; it
    # never influences selection and cannot be treatment-dependent.
    raw_rows = [{k: series[k] for k in ["repo", "instance_id", "base_commit", "problem_statement"]}
                for _, series in rows.iterrows()]
    rng = random.Random(seed)
    rng.shuffle(raw_rows)
    by_repo: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        by_repo.setdefault(str(row["repo"]), []).append(row)
    repo_order = list(by_repo); rng.shuffle(repo_order)
    selected_raw: list[dict[str, Any]] = []
    while len(selected_raw) < size and repo_order:
        next_order = []
        for repo in repo_order:
            bucket = by_repo[repo]
            if bucket and len(selected_raw) < size:
                selected_raw.append(bucket.pop())
            if bucket:
                next_order.append(repo)
        repo_order = next_order
    manager = RepositoryManager(repo_cache, source_root) if repo_cache else None
    enriched: list[dict[str, Any]] = []
    for row in selected_raw:
        issue = str(row["problem_statement"])
        tokens = identifier_like_tokens(issue)
        if manager is not None:
            try:
                token_counts, index_hash = manager.probe_definition_names(str(row["repo"]), str(row["base_commit"]), tokens)
                eligible_counts = {token: token_counts.get(token, 0) for token in tokens if token_counts.get(token, 0) > 0}
                eligible = bool(eligible_counts)
                candidate_count = min(eligible_counts.values()) if eligible_counts else 0
                total_candidate_count = sum(eligible_counts.values())
                bucket = "non_eligible" if not eligible else "1" if candidate_count == 1 else "2-5" if candidate_count <= 5 else ">5"
                status = "computed"
            except Exception:
                eligible, eligible_counts, candidate_count, total_candidate_count, bucket, index_hash, status = False, {}, 0, 0, "unknown_probe_error", None, "unavailable"
        else:
            eligible, eligible_counts, candidate_count, total_candidate_count, bucket, index_hash, status = False, {}, 0, 0, "unknown_no_snapshot", None, "unavailable"
        enriched.append({
            **row, "identifier_like_tokens": tokens, "name_eligible": eligible,
            "name_candidate_count": candidate_count, "ambiguity_bucket": bucket,
            "eligible_identifier_counts": eligible_counts, "name_candidate_total": total_candidate_count,
            "base_commit_index_hash": index_hash,
            "index_status": status,
        })
    if not enriched:
        raise ValueError("The Lite/Verified intersection is empty")
    if len(enriched) < size:
        raise ValueError(f"Only {len(enriched)} intersection rows available; requested {size}")
    selected = sorted(enriched, key=lambda x: x["instance_id"])
    # If snapshots were not available, do not silently claim pre-treatment
    # eligibility. A normal run uses --repo-cache and will have computed values.
    return {
        "schema_version": "1.0",
        "experiment_id": "name_to_definition_phase1",
        "dataset": {
            "name": "SWE-Explore ∩ SWE-bench Verified",
            "verified_path": str(Path(verified_path).resolve()),
            "lite_path": str(Path(lite_path).resolve()),
            "source_url": "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified",
            "source_note": "Local parquet files are authoritative for this run; intersection computed by instance_id.",
            "revision": "local-commit-33a2cfe",
            "intersection_count": len(intersection),
            "sort_rule": "instance_id ascending after verified de-duplication",
        },
        "sampling": {"seed": seed, "requested_size": size, "actual_size": len(selected), "randomization": "seeded Python Mersenne Twister; deterministic bucket/repo ordering"},
        "arms": {
            "baseline": {"extra_tools": [], "common_tools": ["explore_directory", "search_code_with_context", "find_files_containing", "analyze_file_structure", "extract_complete_method", "get_code_relationships", "find_variable_usage", "show_file_imports", "read_file_lines"]},
            "n2d": {"extra_tools": ["find_methods_by_name", "find_all_variables_named"], "common_tools": ["explore_directory", "search_code_with_context", "find_files_containing", "analyze_file_structure", "extract_complete_method", "get_code_relationships", "find_variable_usage", "show_file_imports", "read_file_lines"]},
        },
        "instances": selected,
        "distribution": {
            "repo": dict(Counter(x["repo"] for x in selected)),
            "ambiguity_bucket": dict(Counter(x["ambiguity_bucket"] for x in selected)),
            "name_eligible": dict(Counter(str(x["name_eligible"]).lower() for x in selected)),
        },
        "upstream": {"sgagent_commit": "33a2cfe61d56494ab2d20a2b0c48c1f43e37b452"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--size", type=int, default=45)
    parser.add_argument("--lite", default="dataset/lite.parquet")
    parser.add_argument("--verified", default="dataset/verified.parquet")
    parser.add_argument("--repo-cache")
    parser.add_argument("--source-root")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = build_manifest(args.seed, args.size, args.lite, args.verified, args.repo_cache, args.source_root)
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "instances": len(manifest["instances"]), "distribution": manifest["distribution"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
