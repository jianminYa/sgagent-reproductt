"""Compare two completed, explicitly paired name-to-definition smoke runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PAIR_METRICS = (
    "file_match",
    "class_match",
    "function_match",
    "line_match",
    "line_iou",
    "paper_file_jaccard",
    "paper_function_jaccard",
)
RESOURCE_METRICS = (
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "logical_llm_calls",
    "http_attempts",
    "request_retries",
    "tool_calls",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["instance_id"]] = row
    return rows


def _numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _delta(no_n2d: Any, full14: Any) -> float | None:
    new, old = _numeric(no_n2d), _numeric(full14)
    return None if new is None or old is None else new - old


def _direction(rows: list[dict[str, Any]], metric: str) -> dict[str, int]:
    improved = degraded = tied = 0
    for row in rows:
        delta = row["delta_no_n2d_minus_full14"].get(metric)
        if delta is None:
            continue
        if delta > 0:
            improved += 1
        elif delta < 0:
            degraded += 1
        else:
            tied += 1
    return {"no_n2d_better": improved, "full14_better": degraded, "tie": tied}


def _aggregate_resource_section(full14: dict[str, Any], no_n2d: dict[str, Any], section: str) -> dict[str, Any]:
    full_section = full14.get(section, {})
    no_n2d_section = no_n2d.get(section, {})
    keys = sorted(
        key for key in set(full_section) | set(no_n2d_section)
        if isinstance(full_section.get(key), dict) or isinstance(no_n2d_section.get(key), dict)
    )
    return {
        key: {
            "full14_mean": full_section.get(key, {}).get("mean"),
            "no_n2d_mean": no_n2d_section.get(key, {}).get("mean"),
            "delta_no_n2d_minus_full14_mean": _delta(
                no_n2d_section.get(key, {}).get("mean"),
                full_section.get(key, {}).get("mean"),
            ),
            "full14_median": full_section.get(key, {}).get("median"),
            "no_n2d_median": no_n2d_section.get(key, {}).get("median"),
            "delta_no_n2d_minus_full14_median": _delta(
                no_n2d_section.get(key, {}).get("median"),
                full_section.get(key, {}).get("median"),
            ),
        }
        for key in keys
    }


def build_comparison(full14: dict[str, Any], no_n2d: dict[str, Any], full_rows: dict[str, dict[str, Any]], no_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = sorted(set(full_rows) & set(no_rows))
    if set(full_rows) != set(no_rows):
        raise ValueError("paired runs do not contain the same instance IDs")

    paired = []
    for instance_id in ids:
        full = full_rows[instance_id]
        ablated = no_rows[instance_id]
        paired.append(
            {
                "instance_id": instance_id,
                "full14": {key: full.get(key) for key in ("completed", "termination_reason", *PAIR_METRICS, *RESOURCE_METRICS)},
                "no_n2d": {key: ablated.get(key) for key in ("completed", "termination_reason", *PAIR_METRICS, *RESOURCE_METRICS)},
                "delta_no_n2d_minus_full14": {
                    key: _delta(ablated.get(key), full.get(key)) for key in (*PAIR_METRICS, *RESOURCE_METRICS)
                },
            }
        )

    aggregate_groups = ("official_repository_metrics", "paper_set_jaccard_metrics")
    aggregate_metrics = {}
    for group in aggregate_groups:
        aggregate_metrics[group] = {}
        for key in sorted(set(full14.get(group, {})) | set(no_n2d.get(group, {}))):
            aggregate_metrics[group][key] = {
                "full14": full14.get(group, {}).get(key),
                "no_n2d": no_n2d.get(group, {}).get(key),
                "delta_no_n2d_minus_full14": _delta(no_n2d.get(group, {}).get(key), full14.get(group, {}).get(key)),
            }

    direction = {metric: _direction(paired, metric) for metric in PAIR_METRICS}
    return {
        "status": "paired smoke comparison: full14 versus no_n2d",
        "sample": {"n": len(ids), "instance_ids": ids, "same_instance_set": True},
        "arms": {
            "full14": {key: full14.get(key) for key in ("experiment_id", "n", "completed", "completion_rate", "termination_reasons", "provider_failure", "trace_validation")},
            "no_n2d": {key: no_n2d.get(key) for key in ("experiment_id", "n", "completed", "completion_rate", "termination_reasons", "provider_failure", "trace_validation")},
        },
        "aggregate_metrics": aggregate_metrics,
        "paired_direction": direction,
        "paired_results": paired,
        "aggregate_resource_deltas": {
            section: _aggregate_resource_section(full14, no_n2d, section)
            for section in ("tokens", "calls")
        },
        "notes": [
            "Both arms use the same explicit 10-instance set, model, protocol, timeout, worker count, retry policy, and offline evaluator.",
            "Deltas are no_n2d minus full14; positive values favor no_n2d for metrics and indicate higher resource use for resource fields.",
            "This is pilot-scale paired evidence and does not establish statistical significance or justify scaling beyond the smoke gate by itself.",
        ],
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Paired Full14 versus no-N2D smoke",
        "",
        f"Paired sample size: **{report['sample']['n']}**. Deltas are `no_n2d - full14`.",
        "",
        "## Completion and trace gate",
        "",
        "| Arm | Completed | Rate | Provider failures | Valid traces |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ("full14", "no_n2d"):
        row = report["arms"][arm]
        lines.append(
            f"| {arm} | {row['completed']}/{row['n']} | {_fmt(row['completion_rate'])} | "
            f"{row['provider_failure']['count']} | {row['trace_validation']['valid']}/{row['trace_validation']['checked']} |"
        )
    lines += ["", "## Aggregate metrics", "", "| Group / metric | Full14 | no-N2D | Delta |", "|---|---:|---:|---:|"]
    for group, metrics in report["aggregate_metrics"].items():
        for name, values in metrics.items():
            lines.append(f"| {group} / {name} | {_fmt(values['full14'])} | {_fmt(values['no_n2d'])} | {_fmt(values['delta_no_n2d_minus_full14'])} |")
    lines += ["", "## Per-instance direction", "", "| Metric | no-N2D better | Full14 better | Tie |", "|---|---:|---:|---:|"]
    for metric, values in report["paired_direction"].items():
        lines.append(f"| {metric} | {values['no_n2d_better']} | {values['full14_better']} | {values['tie']} |")
    lines += ["", "## Resource deltas", "", "| Group / metric | Full14 mean | no-N2D mean | Delta | Full14 median | no-N2D median |", "|---|---:|---:|---:|---:|---:|"]
    for group, metrics in report["aggregate_resource_deltas"].items():
        for name, values in metrics.items():
            lines.append(f"| {group} / {name} | {_fmt(values['full14_mean'])} | {_fmt(values['no_n2d_mean'])} | {_fmt(values['delta_no_n2d_minus_full14_mean'])} | {_fmt(values['full14_median'])} | {_fmt(values['no_n2d_median'])} |")
    lines += ["", "## Notes", ""]
    lines.extend(f"- {note}" for note in report["notes"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-report", required=True)
    parser.add_argument("--full-results", required=True)
    parser.add_argument("--no-n2d-report", required=True)
    parser.add_argument("--no-n2d-results", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_comparison(
        _load_json(Path(args.full_report)),
        _load_json(Path(args.no_n2d_report)),
        _load_jsonl(Path(args.full_results)),
        _load_jsonl(Path(args.no_n2d_results)),
    )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "paired_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "paired_comparison.md").write_text(write_markdown(report), encoding="utf-8")
    print(json.dumps({"output": str(output), "n": report["sample"]["n"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
