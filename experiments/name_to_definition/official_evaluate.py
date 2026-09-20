"""Evaluate official Locator reproduction trajectories offline.

The upstream evaluator consumes a patch.  Locator emits ranges, so this file
uses a deterministic synthetic diff only as an adapter to the upstream
``PatchParser``/``ASTAnalyzer``/``MetricsCalculator`` classes.  The adapter is
recorded in the report and never reaches the agent.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .official_locator import _install_python313_lib2to3_stub
from .repo import RepositoryManager


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _load_final(path: Path) -> dict[str, Any] | None:
    finals = [event for event in _load_events(path) if event.get("event_type") == "final"]
    return finals[-1] if finals else None


def _trajectory_static(path: Path) -> dict[str, Any]:
    events = _load_events(path)
    return events[0] if events else {}


def _select_trajectory(run_root: Path, instance_id: str) -> Path:
    """Select the newest successful attempt while retaining failed attempts."""
    instance_root = run_root / instance_id
    candidates = sorted(
        (path / "trajectory.jsonl" for path in instance_root.iterdir()
         if path.is_dir() and path.name.isdigit()),
        key=lambda path: int(path.parent.name), reverse=True,
    ) if instance_root.exists() else []
    for candidate in candidates:
        final = _load_final(candidate)
        if final and final.get("termination_reason") == "completed":
            return candidate
    return candidates[0] if candidates else instance_root / "0" / "trajectory.jsonl"


def _synthetic_patch(locations: list[dict[str, Any]]) -> str:
    """Represent ranked ranges as a parseable, no-content git diff."""
    by_file: dict[str, list[dict[str, Any]]] = {}
    for location in locations or []:
        file_path = str(location.get("file_path", ""))
        start = location.get("start_line")
        end = location.get("end_line")
        if file_path and isinstance(start, int) and isinstance(end, int) and start >= 1 and end >= start:
            by_file.setdefault(file_path, []).append(location)
    chunks: list[str] = []
    for file_path in sorted(by_file):
        chunks.extend([
            f"diff --git a/{file_path} b/{file_path}",
            "index 0000000..0000000 100644",
            f"--- a/{file_path}",
            f"+++ b/{file_path}",
        ])
        for location in by_file[file_path]:
            start = int(location["start_line"])
            count = int(location["end_line"]) - start + 1
            chunks.append(f"@@ -{start},{count} +{start},{count} @@")
            chunks.extend(" " + line for line in [""] * count)
    return "\n".join(chunks) + ("\n" if chunks else "")


def _jaccard(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _stats(values: list[Any]) -> dict[str, Any]:
    clean = sorted(float(value) for value in values if value is not None)
    if not clean:
        return {"n": 0, "mean": None, "median": None, "p25": None, "p75": None,
                "p95": None, "max": None}
    def quantile(q: float) -> float:
        position = (len(clean) - 1) * q
        low, high = math.floor(position), math.ceil(position)
        return clean[low] if low == high else clean[low] + (clean[high] - clean[low]) * (position - low)
    return {
        "n": len(clean), "mean": statistics.mean(clean), "median": statistics.median(clean),
        "p25": quantile(0.25), "p75": quantile(0.75), "p95": quantile(0.95),
        "max": max(clean),
    }


def _metric_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    def mean(name: str) -> float | None:
        values = [float(row[name]) for row in results if row.get(name) is not None]
        return statistics.mean(values) if values else None

    return {
        "n": len(results),
        "completed": sum(bool(row.get("completed")) for row in results),
        "official_repository_metrics": {
            "file_accuracy": mean("file_match"), "class_accuracy": mean("class_match"),
            "function_accuracy": mean("function_match"), "line_accuracy": mean("line_match"),
            "line_iou": mean("line_iou"),
        },
        "paper_set_jaccard_metrics": {
            "file_accuracy": mean("paper_file_jaccard"),
            "function_accuracy": mean("paper_function_jaccard"),
        },
    }


def _bootstrap_ci(values: list[Any], seed: int, resamples: int = 10_000) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"n": 0, "resamples": 0, "lower_2_5": None, "upper_97_5": None}
    rng = random.Random(seed)
    n = len(clean)
    means = []
    for _ in range(resamples):
        means.append(sum(clean[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    low = means[int(0.025 * (resamples - 1))]
    high = means[int(0.975 * (resamples - 1))]
    return {"n": n, "resamples": resamples, "lower_2_5": low, "upper_97_5": high}


def _extract_info(patch: str, root: Path) -> dict[str, Any]:
    # The import is intentionally delayed until the Python 3.13 compatibility
    # shim is installed; this is also the import path used by the repo scorer.
    from script.evaluation.ast_analyzer import ASTAnalyzer
    from script.evaluation.metrics import MetricsCalculator
    from script.evaluation.patch_parser import PatchParser

    file_patches = PatchParser.parse_patch(patch)
    files = [file_patch.new_path for file_patch in file_patches]
    classes_per_file: dict[str, list[str]] = {}
    functions_per_file: dict[str, list[str]] = {}
    lines_per_file: dict[str, list[tuple[int, int]]] = {}
    analyzer = ASTAnalyzer(str(root))
    for file_patch in file_patches:
        path = file_patch.new_path
        ranges = file_patch.get_all_modified_lines()
        try:
            classes_per_file[path] = analyzer.get_classes_at_lines(path, ranges)
        except Exception:
            classes_per_file[path] = []
        try:
            functions_per_file[path] = analyzer.get_function_at_lines(path, ranges)
        except Exception:
            functions_per_file[path] = []
        lines_per_file[path] = ranges
    classes = sorted({name for values in classes_per_file.values() for name in values})
    functions = sorted({name for values in functions_per_file.values() for name in values})
    lines = [line_range for values in lines_per_file.values() for line_range in values]
    return {"files": files, "classes": classes, "functions": functions, "lines": lines}


def _missing_result(item: dict[str, Any], trajectory_path: str) -> dict[str, Any]:
    return {
        "instance_id": item["instance_id"], "repo": item["repo"], "run_id": None,
        "trajectory_path": trajectory_path, "termination_reason": "missing",
        "completed": False, "file_match": False, "class_match": False,
        "function_match": False, "line_match": False, "line_iou": 0.0,
        "paper_file_jaccard": 0.0, "paper_function_jaccard": 0.0,
        "gold_files": [], "predicted_files": [], "gold_functions": [],
        "predicted_functions": [], "gold_line_ranges": [], "predicted_line_ranges": [],
        "token_usage_incomplete": True, "total_tokens": None, "input_tokens": None,
        "output_tokens": None, "locator_llm_calls": 0, "summarizer_llm_calls": 0,
        "logical_llm_calls": 0, "http_attempts": None, "successful_llm_responses": None,
        "failed_llm_calls": None, "nested_llm_calls": None, "request_retries": None,
        "total_llm_calls": 0, "tool_calls": 0, "failed_tool_calls": 0,
        "logical_calls_by_phase": {}, "successful_responses_by_phase": {}, "tokens_by_phase": {},
        "reflection_turns": 0, "wall_clock_ms": None, "cost_usd": None,
        "tool_result_chars": 0, "tool_original_chars": 0, "tool_returned_chars": 0,
        "tool_result_bytes": None, "tool_returned_bytes": None,
        "truncated_tool_calls": 0,
        "tool_output_guard": None, "protocol": None, "provider": None,
        "requested_model": None, "returned_models": [], "request_ids": [], "stop_reasons": {},
    }


def evaluate_one(item: dict[str, Any], row: dict[str, Any], root: Path, trajectory_path: Path) -> dict[str, Any]:
    final = _load_final(trajectory_path)
    if final is None:
        return _missing_result(item, str(trajectory_path))
    from script.evaluation.metrics import MetricsCalculator

    counters = final.get("aggregate_counters", {})
    static = _trajectory_static(trajectory_path)
    predicted_locations = final.get("ranked_locations", []) or []
    gold_info = _extract_info(str(row.get("patch", "")), root)
    predicted_info = _extract_info(_synthetic_patch(predicted_locations), root)
    calc = MetricsCalculator()
    file_match = calc.calculate_file_level_match(gold_info["files"], predicted_info["files"])
    class_match = calc.calculate_class_level_match(gold_info["classes"], predicted_info["classes"])
    function_match = calc.calculate_function_level_match(gold_info["functions"], predicted_info["functions"])
    line_match = calc.calculate_line_level_match(gold_info["lines"], predicted_info["lines"])
    line_iou = calc.calculate_line_level_iou(gold_info["lines"], predicted_info["lines"])
    return {
        "instance_id": item["instance_id"], "repo": item["repo"], "run_id": final.get("run_id"),
        "trajectory_path": str(trajectory_path), "termination_reason": final.get("termination_reason", "missing"),
        "completed": final.get("termination_reason") == "completed",
        "file_match": bool(file_match), "class_match": bool(class_match),
        "function_match": bool(function_match), "line_match": bool(line_match),
        "line_iou": line_iou,
        # These are the paper's stated set-similarity metrics, kept separate
        # from the repository evaluator's containment booleans.
        "paper_file_jaccard": _jaccard(gold_info["files"], predicted_info["files"]),
        "paper_function_jaccard": _jaccard(gold_info["functions"], predicted_info["functions"]),
        "gold_files": gold_info["files"], "predicted_files": predicted_info["files"],
        "gold_classes": gold_info["classes"], "predicted_classes": predicted_info["classes"],
        "gold_functions": gold_info["functions"], "predicted_functions": predicted_info["functions"],
        "gold_line_ranges": gold_info["lines"], "predicted_line_ranges": predicted_info["lines"],
        "predicted_locations": predicted_locations,
        "requested_model": counters.get("requested_model", final.get("model")),
        "returned_models": counters.get("returned_models", []),
        "request_ids": counters.get("request_ids", []),
        "stop_reasons": counters.get("stop_reasons", {}),
        "token_usage_incomplete": bool(counters.get("token_usage_incomplete", True)),
        "total_tokens": counters.get("total_tokens"), "input_tokens": counters.get("input_tokens"),
        "output_tokens": counters.get("output_tokens"),
        "locator_llm_calls": counters.get("locator_llm_calls", 0),
        "summarizer_llm_calls": counters.get("summarizer_llm_calls", 0),
        "logical_llm_calls": counters.get("logical_llm_calls", counters.get("total_llm_calls", 0)),
        "http_attempts": counters.get("http_attempts"),
        "successful_llm_responses": counters.get("successful_llm_responses"),
        "failed_llm_calls": counters.get("failed_llm_calls"),
        "nested_llm_calls": counters.get("nested_llm_calls"),
        "request_retries": counters.get("request_retries"),
        "total_llm_calls": counters.get("total_llm_calls", 0),
        "logical_calls_by_phase": counters.get("logical_calls_by_phase", {}),
        "successful_responses_by_phase": counters.get("successful_responses_by_phase", {}),
        "tokens_by_phase": counters.get("tokens_by_phase", {}),
        "tool_calls": counters.get("tool_calls", 0), "failed_tool_calls": counters.get("failed_tool_calls", 0),
        "reflection_turns": counters.get("reflection_turns", 0),
        "tool_result_chars": counters.get("tool_result_chars", 0),
        "tool_original_chars": counters.get("tool_original_chars", 0),
        "tool_returned_chars": counters.get("tool_returned_chars", 0),
        "tool_result_bytes": counters.get("tool_original_bytes"),
        "tool_returned_bytes": counters.get("tool_returned_bytes"),
        "truncated_tool_calls": counters.get("truncated_tool_calls", 0),
        "tool_output_guard": static.get("tool_output_guard"),
        "protocol": static.get("protocol"), "provider": static.get("provider"),
        "wall_clock_ms": counters.get("wall_clock_ms"), "cost_usd": None,
    }


def aggregate(results: list[dict[str, Any]], manifest: dict[str, Any], experiment_id: str | None = None) -> dict[str, Any]:
    n = len(results)
    def mean(name: str) -> float | None:
        values = [float(row[name]) for row in results if row.get(name) is not None]
        return statistics.mean(values) if values else None
    completed = sum(row["completed"] for row in results)
    completed_rows = [row for row in results if row.get("completed")]
    operational_metrics = _metric_summary(results)
    completed_metrics = _metric_summary(completed_rows)
    tool_usage: Counter[str] = Counter()
    failed_tool_usage: Counter[str] = Counter()
    for row in results:
        for event in _load_events(Path(row["trajectory_path"])):
            if event.get("event_type") != "tool_call":
                continue
            name = str(event.get("tool_name") or "unknown")
            tool_usage[name] += 1
            if not event.get("success"):
                failed_tool_usage[name] += 1
    returned_models: Counter[str] = Counter()
    stop_reasons: Counter[str] = Counter()
    request_ids = []
    guard_values = []
    protocols = Counter()
    providers = Counter()
    for row in results:
        returned_models.update(str(model) for model in row.get("returned_models", []))
        stop_reasons.update({str(reason): int(count) for reason, count in (row.get("stop_reasons") or {}).items()})
        request_ids.extend(row.get("request_ids", []))
        if row.get("tool_output_guard") is not None:
            guard_values.append(bool(row["tool_output_guard"]))
        if row.get("protocol"):
            protocols[str(row["protocol"])] += 1
        if row.get("provider"):
            providers[str(row["provider"])] += 1
    try:
        from .trace_validator import validate_trace
        trace_checks = [validate_trace(row["trajectory_path"]) for row in results]
        trace_validation = {
            "checked": len(trace_checks),
            "valid": sum(bool(check["valid"]) for check in trace_checks),
            "invalid": sum(not bool(check["valid"]) for check in trace_checks),
            "note": "Inherited Phase2 successful trajectories may be legacy traces; no successful sample was rerun for migration.",
            "invalid_examples": [
                {"trajectory": row["trajectory_path"], "errors": check["errors"][:5]}
                for row, check in zip(results, trace_checks) if not check["valid"]
            ][:10],
        }
    except Exception as exc:
        trace_validation = {"checked": 0, "valid": 0, "invalid": 0,
                            "validator_error": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "official Locator reproduction; pilot-scale evidence",
        "experiment_id": experiment_id or manifest["experiment_id"], "n": n,
        "completed": completed, "completion_rate": completed / n if n else None,
        "termination_reasons": dict(Counter(row["termination_reason"] for row in results)),
        "official_repository_metrics": operational_metrics["official_repository_metrics"],
        "paper_set_jaccard_metrics": operational_metrics["paper_set_jaccard_metrics"],
        "operational_metrics": operational_metrics,
        "completed_only_conditional_metrics": completed_metrics,
        "bootstrap_ci_95": {
            "completion_rate": _bootstrap_ci([bool(row["completed"]) for row in results], 20260915),
            "official_repository_metrics": {
                name: _bootstrap_ci([row[field] for row in results], 20260915 + index)
                for index, (name, field) in enumerate((
                    ("file_accuracy", "file_match"), ("class_accuracy", "class_match"),
                    ("function_accuracy", "function_match"), ("line_accuracy", "line_match"),
                    ("line_iou", "line_iou"),
                ))
            },
            "paper_set_jaccard_metrics": {
                name: _bootstrap_ci([row[field] for row in results], 20260925 + index)
                for index, (name, field) in enumerate((
                    ("file_accuracy", "paper_file_jaccard"),
                    ("function_accuracy", "paper_function_jaccard"),
                ))
            },
            "tokens": {
                name: _bootstrap_ci([row[field] for row in results], 20260935 + index)
                for index, (name, field) in enumerate((
                    ("total", "total_tokens"), ("input", "input_tokens"),
                    ("output", "output_tokens"),
                ))
            },
        },
        "tokens": {
            "incomplete_trajectories": sum(bool(row["token_usage_incomplete"]) for row in results),
            "total": _stats([row["total_tokens"] for row in results]),
            "input": _stats([row["input_tokens"] for row in results]),
            "output": _stats([row["output_tokens"] for row in results]),
        },
        "completed_only_tokens": {
            "total": _stats([row["total_tokens"] for row in completed_rows]),
            "input": _stats([row["input_tokens"] for row in completed_rows]),
            "output": _stats([row["output_tokens"] for row in completed_rows]),
        },
        "calls": {
            "locator_llm": _stats([row["locator_llm_calls"] for row in results]),
            "summarizer_llm": _stats([row["summarizer_llm_calls"] for row in results]),
            "total_llm": _stats([row["total_llm_calls"] for row in results]),
            "tools": _stats([row["tool_calls"] for row in results]),
            "failed_tools": _stats([row["failed_tool_calls"] for row in results]),
            "logical_llm": _stats([row["logical_llm_calls"] for row in results]),
            "http_attempts": _stats([row["http_attempts"] for row in results]),
            "successful_responses": _stats([row["successful_llm_responses"] for row in results]),
            "failed_logical_llm": _stats([row["failed_llm_calls"] for row in results]),
            "request_retries": _stats([row["request_retries"] for row in results]),
        },
        "tool_output": {
            "original_chars": _stats([row["tool_original_chars"] for row in results]),
            "returned_chars": _stats([row["tool_returned_chars"] for row in results]),
            "original_bytes": _stats([row["tool_result_bytes"] for row in results]),
            "returned_bytes": _stats([row["tool_returned_bytes"] for row in results]),
            "truncated_calls": _stats([row["truncated_tool_calls"] for row in results]),
            "trajectories_with_truncation": sum(bool(row["truncated_tool_calls"]) for row in results),
            "guard_enabled_values": dict(Counter(str(value) for value in guard_values)),
            "guard_all_disabled": bool(guard_values) and not any(guard_values),
        },
        "tool_usage_patterns": {
            "calls": dict(sorted(tool_usage.items())),
            "failed_calls": dict(sorted(failed_tool_usage.items())),
        },
        "latency_ms": _stats([row["wall_clock_ms"] for row in results]),
        "provider_failure": {
            "count": sum(row.get("termination_reason") == "api_error" for row in results),
            "rate": (sum(row.get("termination_reason") == "api_error" for row in results) / n) if n else None,
            "definition": "trajectory termination_reason == api_error; HTTP attempts are separately counted",
        },
        "trace_validation": trace_validation,
        "token_extremes": {
            "highest": sorted(
                ({"instance_id": row["instance_id"], "total_tokens": row["total_tokens"]} for row in results if row.get("total_tokens") is not None),
                key=lambda value: value["total_tokens"], reverse=True,
            )[:5],
            "lowest": sorted(
                ({"instance_id": row["instance_id"], "total_tokens": row["total_tokens"]} for row in results if row.get("total_tokens") is not None),
                key=lambda value: value["total_tokens"],
            )[:5],
        },
        "cost_usd": None,
        "cost_note": "qtapi pricing was not supplied; no fabricated cost estimate is reported.",
        "model_metadata": {
            "requested_models": dict(Counter(str(row.get("requested_model")) for row in results if row.get("requested_model"))),
            "returned_models": dict(sorted(returned_models.items())),
            "request_ids_recorded": len(request_ids),
            "request_ids_unique": len(set(request_ids)),
            "request_ids_missing": sum(row["total_llm_calls"] for row in results) - len(request_ids),
            "stop_reasons": dict(sorted(stop_reasons.items())),
            "protocols": dict(sorted(protocols.items())),
            "providers": dict(sorted(providers.items())),
        },
        "evaluation_adapter": {
            "predicted_ranges_as_synthetic_diff": True,
            "official_evaluator_classes": "script.evaluation.PatchParser, ASTAnalyzer, MetricsCalculator",
            "gold_source": "local Lite parquet patch; agent never receives patch",
        },
        "sampling": manifest["sampling"], "dataset": manifest["dataset"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--lite", default="dataset/lite.parquet")
    parser.add_argument("--repo-cache", default="experiments/name_to_definition/repo_cache")
    parser.add_argument("--source-root")
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment-id", help="Override the manifest label for this reproduction report.")
    parser.add_argument("--instances", help="Comma-separated instance IDs to evaluate from the manifest.")
    args = parser.parse_args()
    _install_python313_lib2to3_stub()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.instances:
        selected_ids = {value.strip() for value in args.instances.split(",") if value.strip()}
        selected_instances = [item for item in manifest["instances"] if item["instance_id"] in selected_ids]
        missing_ids = selected_ids - {item["instance_id"] for item in selected_instances}
        if missing_ids:
            raise SystemExit(f"unknown instance IDs: {sorted(missing_ids)}")
        manifest = {
            **manifest,
            "instances": selected_instances,
            "sampling": {
                **manifest.get("sampling", {}),
                "requested_size": len(selected_instances),
                "actual_size": len(selected_instances),
                "method": "explicit paired-smoke instance IDs",
                "instance_filter": [item["instance_id"] for item in selected_instances],
            },
        }
    df = pd.read_parquet(args.lite)
    rows = {str(row.instance_id): row._asdict() for row in df.itertuples(index=False)}
    manager = RepositoryManager(args.repo_cache, args.source_root)
    results: list[dict[str, Any]] = []
    run_root = Path(args.runs)
    for item in manifest["instances"]:
        row = rows[item["instance_id"]]
        trajectory = _select_trajectory(run_root, item["instance_id"])
        with manager.materialize(item["repo"], item["base_commit"]) as root:
            results.append(evaluate_one(item, row, root, trajectory))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "instance_results.jsonl").write_text(
        "\n".join(json.dumps(result, ensure_ascii=False, default=str) for result in results) + "\n", encoding="utf-8"
    )
    fields = sorted({key for result in results for key in result})
    with (output / "instance_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    report = aggregate(results, manifest, args.experiment_id)
    (output / "aggregate_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    official = report["official_repository_metrics"]
    paper = report["paper_set_jaccard_metrics"]
    lines = [
        "# Official SGAgent Locator reproduction",
        "",
        "This report covers the official Locator workflow only; no name-to-definition arm was run.",
        "",
        f"- Instances: {report['n']} seeded Lite instances; completed Locator outputs: {report['completed']} ({report['completion_rate']}).",
        f"- Termination: `{report['termination_reasons']}`.",
        f"- Official repository evaluator: File={official['file_accuracy']}, Class={official['class_accuracy']}, Function={official['function_accuracy']}, Line={official['line_accuracy']}, IoU={official['line_iou']}.",
        f"- Paper set-Jaccard adapter: File={paper['file_accuracy']}, Function={paper['function_accuracy']}.",
        f"- Completed-only conditional metrics: {report['completed_only_conditional_metrics']}.",
        f"- Provider failure: {report['provider_failure']}; HTTP attempts mean/p95/max: {report['calls']['http_attempts']['mean']} / {report['calls']['http_attempts']['p95']} / {report['calls']['http_attempts']['max']}.",
        f"- Bootstrap 95% CI (percentile, 10,000 resamples): official={report['bootstrap_ci_95']['official_repository_metrics']}; paper-Jaccard={report['bootstrap_ci_95']['paper_set_jaccard_metrics']}.",
        f"- Total-token mean/median/p95/max: {report['tokens']['total']['mean']} / {report['tokens']['total']['median']} / {report['tokens']['total']['p95']} / {report['tokens']['total']['max']}; incomplete trajectories: {report['tokens']['incomplete_trajectories']}.",
        f"- Token extremes: highest={report['token_extremes']['highest']}; lowest={report['token_extremes']['lowest']}.",
        f"- LLM-call mean: {report['calls']['total_llm']['mean']}; tool-call mean: {report['calls']['tools']['mean']}; latency mean ms: {report['latency_ms']['mean']}.",
        f"- Tool-output guard: original/returned chars mean {report['tool_output']['original_chars']['mean']} / {report['tool_output']['returned_chars']['mean']}; truncated calls mean {report['tool_output']['truncated_calls']['mean']}; trajectories with truncation {report['tool_output']['trajectories_with_truncation']}.",
        f"- Experiment-layer 32,000-character guard enabled values: {report['tool_output']['guard_enabled_values']}; all disabled: {report['tool_output']['guard_all_disabled']}.",
        f"- Tool usage: {report['tool_usage_patterns']['calls']}.",
        f"- Requested models: {report['model_metadata']['requested_models']}; returned models: {report['model_metadata']['returned_models']}; request IDs recorded/unique/missing: {report['model_metadata']['request_ids_recorded']}/{report['model_metadata']['request_ids_unique']}/{report['model_metadata']['request_ids_missing']}; stop reasons: {report['model_metadata']['stop_reasons']}.",
        f"- Trace validation: {report['trace_validation']}.",
        "- Cost: not reported because qtapi pricing was not supplied.",
        "",
        "The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.",
        "Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.",
        "",
        "See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.",
    ]
    (output / "aggregate_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"results": len(results), "output": str(output), "aggregate": report}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
