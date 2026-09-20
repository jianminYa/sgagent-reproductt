"""Offline Locator evaluator and paired pilot report generator."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .index import RepositoryIndex
from .repo import RepositoryManager


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def gold_hunks(patch: str) -> list[dict[str, Any]]:
    lines = patch.splitlines()
    current = None; result = []
    for line in lines:
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match and current:
            old_start, old_count, new_start, new_count = [int(x or 1) for x in match.groups()]
            if old_count == 0:
                start, end = new_start, new_start + max(new_count, 1) - 1
            else:
                start, end = old_start, old_start + old_count - 1
            result.append({"file_path": current, "start_line": start, "end_line": end})
    return result


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start) + 1)


def _iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    inter = _overlap(a_start, a_end, b_start, b_end)
    union = max(a_end, b_end) - min(a_start, b_start) + 1
    return inter / union if union else 0.0


def _load_final(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    last = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
            if obj.get("event_type") == "final":
                last = obj
        except json.JSONDecodeError:
            continue
    return last


def _load_events(path: Path) -> list[dict[str, Any]]:
    events = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def _stats(values: list[float | int | None]) -> dict[str, Any]:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None}
    def quantile(q: float) -> float:
        pos = (len(clean) - 1) * q; lo = math.floor(pos); hi = math.ceil(pos)
        return clean[lo] if lo == hi else clean[lo] + (clean[hi] - clean[lo]) * (pos - lo)
    return {"n": len(clean), "mean": statistics.mean(clean), "median": statistics.median(clean), "p25": quantile(.25), "p75": quantile(.75)}


def bootstrap_ci(values: list[float], seed: int = 20260915, rounds: int = 2000) -> list[float | None]:
    if not values:
        return [None, None]
    rng = random.Random(seed); means = []
    for _ in range(rounds):
        means.append(statistics.mean(rng.choice(values) for _ in values))
    means.sort()
    return [means[int(.025 * (len(means) - 1))], means[int(.975 * (len(means) - 1))]]


def _method_hit(index: RepositoryIndex, gold: list[dict[str, Any]], predicted: list[dict[str, Any]]) -> bool:
    for g in gold:
        for m in index.metadata_for_file(g["file_path"]):
            if _overlap(m["start_line"], m["end_line"], g["start_line"], g["end_line"]):
                if any(p["file_path"] == m["file_path"] and _overlap(p["start_line"], p["end_line"], m["start_line"], m["end_line"]) for p in predicted):
                    return True
    return False


def evaluate_run(final: dict[str, Any], row: dict[str, Any], index: RepositoryIndex, events: list[dict[str, Any]] | None = None, trajectory_path: str | None = None) -> dict[str, Any]:
    counters = final.get("aggregate_counters", {}) if final else {}
    def counter(name: str, default: Any = None) -> Any:
        return counters.get(name, final.get(name, default) if final else default)

    gold = gold_hunks(str(row.get("patch", "")))
    predicted = final.get("ranked_locations", []) if final else []
    files = {g["file_path"] for g in gold}
    file_hit = any(p.get("file_path") in files for p in predicted)
    ious = [max((_iou(p["start_line"], p["end_line"], g["start_line"], g["end_line"])
                for g in gold if p.get("file_path") == g["file_path"]), default=0.0) for p in predicted]
    max_iou = max(ious, default=0.0)
    line_hit = max_iou > 0
    function_hit = _method_hit(index, gold, predicted)
    gold_methods = [m for g in gold for m in index.metadata_for_file(g["file_path"])
                    if _overlap(m["start_line"], m["end_line"], g["start_line"], g["end_line"])]
    eligible_tokens = row.get("identifier_like_tokens", []) or []
    # The manifest records full-repository candidate counts during sampling.
    # Use those counts here because the evaluation index is intentionally
    # limited to gold files for speed; function-hit checks remain exact.
    indexed_counts = row.get("eligible_identifier_counts") or {}
    index_candidate_count = sum(int(value) for value in indexed_counts.values()) if indexed_counts else sum(
        len(index.definitions(kind, token, "exact"))
        for token in eligible_tokens for kind in ("method", "variable")
    )
    n2d_candidates: list[dict[str, Any]] = []
    first_gold_event = None
    if events:
        tool_events = [e for e in events if e.get("event_type") == "tool_call"]
        for e in tool_events:
            result_text = str(e.get("result") or "")
            if any(g["file_path"] in result_text for g in gold):
                first_gold_event = e
            if e.get("tool_name") in {"find_methods_by_name", "find_all_variables_named"} and e.get("success"):
                try:
                    obj = json.loads(result_text)
                    n2d_candidates.extend(obj.get("candidates", []))
                except (json.JSONDecodeError, TypeError):
                    pass
    gold_candidate_rank = None
    for pos, candidate in enumerate(n2d_candidates, 1):
        if any(candidate.get("file_path") == m["file_path"] and _overlap(candidate.get("start_line", 0), candidate.get("end_line", 0), m["start_line"], m["end_line"]) for m in gold_methods):
            gold_candidate_rank = pos; break
    first_calls = first_gold_event.get("seq") if first_gold_event else None
    before_gold = events[:events.index(first_gold_event)] if first_gold_event and first_gold_event in events else []
    prior_llm_tokens = [e.get("token_usage", {}).get("total_tokens") for e in before_gold if e.get("event_type") == "llm_response"]
    return {
        "run_id": final.get("run_id") if final else None,
        "instance_id": row["instance_id"], "arm": final.get("arm") if final else None,
        "termination_reason": final.get("termination_reason", "missing") if final else "missing",
        "token_usage_incomplete": counter("token_usage_incomplete", True),
        "total_tokens": counter("total_tokens"),
        "locator_llm_calls": counter("locator_llm_calls", 0), "tool_calls": counter("tool_calls", 0),
        "failed_tool_calls": counter("failed_tool_calls", 0), "reflection_turns": counter("reflection_turns", 0),
        "wall_clock_ms": counter("wall_clock_ms"), "file_hit": int(file_hit),
        "function_hit": int(function_hit), "line_hit": int(line_hit), "max_line_iou": max_iou,
        "gold_files": sorted(files), "predicted_locations": predicted,
        "name_eligible": row.get("name_eligible"), "ambiguity_bucket": row.get("ambiguity_bucket"),
        "issue_identifier_count": len(eligible_tokens), "index_candidate_count": index_candidate_count,
        "gold_definition_in_candidates": gold_candidate_rank is not None,
        "gold_candidate_rank": gold_candidate_rank,
        "recall_at_1": int(gold_candidate_rank is not None and gold_candidate_rank <= 1),
        "recall_at_3": int(gold_candidate_rank is not None and gold_candidate_rank <= 3),
        "recall_at_5": int(gold_candidate_rank is not None and gold_candidate_rank <= 5),
        "first_gold_event_seq": first_calls,
        "first_gold_llm_calls": sum(e.get("event_type") == "llm_response" for e in before_gold),
        "first_gold_tool_calls": sum(e.get("event_type") == "tool_call" for e in before_gold),
        "first_gold_tokens": sum(prior_llm_tokens) if prior_llm_tokens and all(v is not None for v in prior_llm_tokens) else None,
        "trajectory_path": trajectory_path,
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results: by_arm[r["arm"]].append(r)
    aggregate = {"pilot_status": "pilot evidence", "real_pilot_ran": True,
                 "pilot_scope": "45 sampled intersection instances x 2 arms = 90 real Claude trajectories",
                 "by_arm": {}, "paired": {},
                 "official_swe_explore_metrics": None,
                 "official_swe_explore_note": "Official scorer not bundled in this repository; fields are intentionally null."}
    for arm, rows in by_arm.items():
        aggregate["by_arm"][arm] = {
            "n": len(rows), "completed": sum(r["termination_reason"] == "completed" for r in rows),
            "failed": sum(r["termination_reason"] not in {"completed"} for r in rows),
            "token_usage_incomplete": sum(bool(r["token_usage_incomplete"]) for r in rows),
            "termination_reasons": dict(Counter(r["termination_reason"] for r in rows)),
            "total_tokens": _stats([r["total_tokens"] for r in rows if not r["token_usage_incomplete"]]),
            "locator_llm_calls": _stats([r["locator_llm_calls"] for r in rows]),
            "tool_calls": _stats([r["tool_calls"] for r in rows]),
            "failed_tool_calls": _stats([r["failed_tool_calls"] for r in rows]),
            "file_accuracy": statistics.mean(r["file_hit"] for r in rows) if rows else None,
            "function_accuracy": statistics.mean(r["function_hit"] for r in rows) if rows else None,
            "line_hit_rate": statistics.mean(r["line_hit"] for r in rows) if rows else None,
            "line_iou": statistics.mean(r["max_line_iou"] for r in rows) if rows else None,
            "first_gold_tokens": _stats([r.get("first_gold_tokens") for r in rows]),
            "first_gold_llm_calls": _stats([r.get("first_gold_llm_calls") for r in rows]),
            "first_gold_tool_calls": _stats([r.get("first_gold_tool_calls") for r in rows]),
        }
        if arm == "n2d":
            ranked_rows = [r for r in rows if r["gold_candidate_rank"] is not None]
            aggregate["by_arm"][arm].update({
                "lookup_gold_definition_in_candidates": sum(bool(r["gold_definition_in_candidates"]) for r in rows),
                "lookup_recall_at_1": statistics.mean(r["recall_at_1"] for r in rows) if rows else None,
                "lookup_recall_at_3": statistics.mean(r["recall_at_3"] for r in rows) if rows else None,
                "lookup_recall_at_5": statistics.mean(r["recall_at_5"] for r in rows) if rows else None,
                "lookup_rank_defined_n": sum(r["gold_candidate_rank"] is not None for r in rows),
                "lookup_recall_at_1_defined": statistics.mean(r["recall_at_1"] for r in ranked_rows) if ranked_rows else None,
                "lookup_recall_at_3_defined": statistics.mean(r["recall_at_3"] for r in ranked_rows) if ranked_rows else None,
                "lookup_recall_at_5_defined": statistics.mean(r["recall_at_5"] for r in ranked_rows) if ranked_rows else None,
            })
    tool_patterns: dict[str, dict[str, dict[str, int]]] = {}
    for arm, rows in by_arm.items():
        counts: Counter[str] = Counter(); successes: Counter[str] = Counter(); failures: Counter[str] = Counter()
        for row in rows:
            path = row.get("trajectory_path")
            if not path:
                continue
            for event in _load_events(Path(path)):
                if event.get("event_type") != "tool_call":
                    continue
                name = str(event.get("tool_name") or "unknown")
                counts[name] += 1
                (successes if event.get("success") else failures)[name] += 1
        tool_patterns[arm] = {
            "calls": dict(sorted(counts.items())),
            "successful_calls": dict(sorted(successes.items())),
            "failed_calls": dict(sorted(failures.items())),
        }
    aggregate["tool_usage_patterns"] = tool_patterns
    paired: dict[str, dict[str, float]] = {}
    arms = set(by_arm)
    if {"baseline", "n2d"} <= arms:
        base = {r["instance_id"]: r for r in by_arm["baseline"]}; n2d = {r["instance_id"]: r for r in by_arm["n2d"]}
        common = sorted(set(base) & set(n2d))
        deltas = {}
        for field in ["total_tokens", "locator_llm_calls", "tool_calls", "file_hit", "function_hit", "max_line_iou"]:
            values = [float(n2d[i][field]) - float(base[i][field]) for i in common if n2d[i].get(field) is not None and base[i].get(field) is not None]
            deltas[field] = {"n": len(values), "mean": statistics.mean(values) if values else None, "median": statistics.median(values) if values else None, "bootstrap_95_ci": bootstrap_ci(values)}
        paired["baseline_minus_n2d_note"] = {"instances": len(common), "delta_defined_as_n2d_minus_baseline": deltas}
    aggregate["paired"] = paired
    if {"baseline", "n2d"} <= arms:
        base = {r["instance_id"]: r for r in by_arm["baseline"]}; n2d = {r["instance_id"]: r for r in by_arm["n2d"]}
        examples = {"reduced_calls": [], "no_improvement": [], "regression": []}
        for instance_id in sorted(set(base) & set(n2d)):
            b, t = base[instance_id], n2d[instance_id]
            delta = {"instance_id": instance_id, "baseline_trajectory": b.get("trajectory_path"), "n2d_trajectory": t.get("trajectory_path"),
                     "delta_tool_calls": t["tool_calls"] - b["tool_calls"], "delta_total_tokens": None if t.get("total_tokens") is None or b.get("total_tokens") is None else t["total_tokens"] - b["total_tokens"],
                     "baseline_termination": b["termination_reason"], "n2d_termination": t["termination_reason"]}
            if delta["delta_tool_calls"] < 0: examples["reduced_calls"].append(delta)
            elif delta["delta_tool_calls"] > 0: examples["regression"].append(delta)
            else: examples["no_improvement"].append(delta)
        aggregate["trajectory_contrast_examples"] = {key: value[:3] for key, value in examples.items()}
    for group_name, predicate in [("name_eligible", lambda r: r.get("name_eligible") is True), ("non_eligible", lambda r: r.get("name_eligible") is False), ("ambiguity_1", lambda r: r.get("ambiguity_bucket") == "1"), ("ambiguity_2-5", lambda r: r.get("ambiguity_bucket") == "2-5"), ("ambiguity_>5", lambda r: r.get("ambiguity_bucket") == ">5")]:
        group = [r for r in results if predicate(r)]
        aggregate.setdefault("subgroups", {})[group_name] = {"n": len(group), "file_accuracy": statistics.mean(r["file_hit"] for r in group) if group else None, "function_accuracy": statistics.mean(r["function_hit"] for r in group) if group else None, "line_iou": statistics.mean(r["max_line_iou"] for r in group) if group else None}
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", required=True)
    parser.add_argument("--manifest", default="experiments/name_to_definition/manifests/pilot_45_seed_20260915.json")
    parser.add_argument("--verified", default="dataset/verified.parquet")
    parser.add_argument("--repo-cache", default="experiments/name_to_definition/repo_cache")
    parser.add_argument("--source-root")
    parser.add_argument("--output", default="experiments/name_to_definition/reports")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    df = pd.read_parquet(args.verified); rows = {str(r.instance_id): r._asdict() for r in df.itertuples(index=False)}
    results = []; manager = RepositoryManager(args.repo_cache, args.source_root)
    run_root = Path(args.runs)
    for item in manifest["instances"]:
        row = {**item, **rows[str(item["instance_id"])]}
        # Both arms use the same immutable source snapshot.  Materialize and
        # index it once per instance so evaluation remains practical at pilot
        # size while preserving exact paired comparisons.
        with manager.materialize(str(row["repo"]), str(row["base_commit"])) as root:
            gold_file_paths = {g["file_path"] for g in gold_hunks(str(row.get("patch", "")))}
            index = RepositoryIndex(root, only_files=gold_file_paths)
            for arm in ("baseline", "n2d"):
                final_path = run_root / arm / str(item["instance_id"]) / "0" / "trajectory.jsonl"
                final = _load_final(final_path)
                if final is None:
                    results.append({"run_id": None, "instance_id": row["instance_id"], "arm": arm,
                                    "termination_reason": "missing", "token_usage_incomplete": True,
                                    "total_tokens": None, "locator_llm_calls": 0, "tool_calls": 0,
                                    "failed_tool_calls": 0, "reflection_turns": 0, "wall_clock_ms": None,
                                    "file_hit": 0, "function_hit": 0, "line_hit": 0, "max_line_iou": 0.0,
                                    "gold_files": sorted({g["file_path"] for g in gold_hunks(str(row.get("patch", "")))}),
                                    "predicted_locations": [], "name_eligible": row.get("name_eligible"),
                                    "ambiguity_bucket": row.get("ambiguity_bucket"), "issue_identifier_count": len(row.get("identifier_like_tokens", []) or []),
                                    "index_candidate_count": None, "gold_definition_in_candidates": False,
                                    "gold_candidate_rank": None, "recall_at_1": 0, "recall_at_3": 0, "recall_at_5": 0,
                                    "first_gold_event_seq": None})
                    continue
                (final_path.parent / "summary.json").write_text(
                    json.dumps({"schema_version": "1.0", **final.get("aggregate_counters", {}),
                                "run_id": final.get("run_id"), "arm": arm,
                                "instance_id": item["instance_id"]}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                results.append(evaluate_run(final, row, index, _load_events(final_path), str(final_path)))
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    jsonl = out / "instance_results.jsonl"
    jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in results) + "\n", encoding="utf-8")
    fields = sorted({key for row in results for key in row})
    with (out / "instance_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(results)
    aggregate = _aggregate(results); (out / "aggregate_report.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    b = aggregate["by_arm"].get("baseline", {})
    t = aggregate["by_arm"].get("n2d", {})
    delta = aggregate.get("paired", {}).get("baseline_minus_n2d_note", {}).get("delta_defined_as_n2d_minus_baseline", {})
    md = "\n".join([
        "# Name-to-definition phase-one pilot",
        "",
        "Status: real pilot ran; results are pilot evidence only and do not establish a general causal claim.",
        "",
        "## Scope",
        "",
        "- 45 seeded instances from the exact SWE-Explore ∩ SWE-bench Verified intersection.",
        "- 2 locator-only arms, 90 real `claude-sonnet-5` trajectories.",
        "- Gold locations were parsed offline from the SWE-bench patch; the agent never received the patch.",
        "",
        "## Aggregate results",
        "",
        "| arm | file accuracy | function accuracy | line hit rate | mean tokens | mean tool calls | incomplete tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| baseline | {b.get('file_accuracy')} | {b.get('function_accuracy')} | {b.get('line_hit_rate')} | {b.get('total_tokens', {}).get('mean')} | {b.get('tool_calls', {}).get('mean')} | {b.get('token_usage_incomplete')} |",
        f"| n2d | {t.get('file_accuracy')} | {t.get('function_accuracy')} | {t.get('line_hit_rate')} | {t.get('total_tokens', {}).get('mean')} | {t.get('tool_calls', {}).get('mean')} | {t.get('token_usage_incomplete')} |",
        "",
        f"N2D lookup recall over all 45 instances: R@1={t.get('lookup_recall_at_1')}, R@3={t.get('lookup_recall_at_3')}, R@5={t.get('lookup_recall_at_5')}; among the {t.get('lookup_rank_defined_n')} instances with a ranked gold candidate: R@1={t.get('lookup_recall_at_1_defined')}, R@3={t.get('lookup_recall_at_3_defined')}, R@5={t.get('lookup_recall_at_5_defined')}.",
        "",
        "## Paired deltas",
        "",
        "Deltas are n2d minus baseline; confidence intervals are bootstrap 95% CIs.",
        "",
        *[f"- `{name}`: mean={value.get('mean')}, CI={value.get('bootstrap_95_ci')}" for name, value in delta.items()],
        "",
        "Official SWE-Explore scorer fields are intentionally null because the scorer is not bundled in this repository.",
        "See `aggregate_report.json` and `instance_results.csv` for subgroups, tool patterns, contrast examples, and per-instance evidence.",
        "",
    ])
    (out / "aggregate_report.md").write_text(md, encoding="utf-8")
    print(json.dumps({"results": len(results), "output": str(out), "by_arm": aggregate["by_arm"]}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
