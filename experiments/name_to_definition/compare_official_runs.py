"""Compare the preserved five-tool run with the full 14-tool reproduction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _delta(full: Any, five: Any) -> float | None:
    if not isinstance(full, (int, float)) or not isinstance(five, (int, float)):
        return None
    return float(full) - float(five)


def _metric_block(report: dict[str, Any], name: str) -> dict[str, Any]:
    return dict(report.get(name, {}))


def _stat_value(block: Any, stat: str) -> Any:
    if isinstance(block, dict):
        return block.get(stat)
    return block if stat == "n" and isinstance(block, (int, float)) else None


def build_comparison(five: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    metric_groups = {
        "official_repository_metrics": _metric_block(five, "official_repository_metrics"),
        "paper_set_jaccard_metrics": _metric_block(five, "paper_set_jaccard_metrics"),
    }
    metric_comparison: dict[str, Any] = {}
    for group in metric_groups:
        keys = sorted(set(metric_groups[group]) | set(_metric_block(full, group)))
        metric_comparison[group] = {
            key: {
                "five_tool": five.get(group, {}).get(key),
                "full14": full.get(group, {}).get(key),
                "delta_full14_minus_five_tool": _delta(
                    full.get(group, {}).get(key), five.get(group, {}).get(key)
                ),
            }
            for key in keys
        }

    stat_comparison: dict[str, Any] = {}
    for section in ("tokens", "calls"):
        stat_comparison[section] = {}
        keys = sorted(
            key for key in (set(five.get(section, {})) | set(full.get(section, {})))
            if isinstance(five.get(section, {}).get(key), dict)
            or isinstance(full.get(section, {}).get(key), dict)
        )
        for key in keys:
            old = five.get(section, {}).get(key, {})
            new = full.get(section, {}).get(key, {})
            stat_comparison[section][key] = {
                stat: {
                    "five_tool": _stat_value(old, stat),
                    "full14": _stat_value(new, stat),
                    "delta_full14_minus_five_tool": _delta(
                        _stat_value(new, stat),
                        _stat_value(old, stat),
                    ),
                }
                for stat in ("n", "mean", "median", "p25", "p75")
            }
    stat_comparison["latency_ms"] = {
        "latency_ms": {
            stat: {
                "five_tool": five.get("latency_ms", {}).get(stat),
                "full14": full.get("latency_ms", {}).get(stat),
                "delta_full14_minus_five_tool": _delta(
                    full.get("latency_ms", {}).get(stat), five.get("latency_ms", {}).get(stat)
                ),
            }
            for stat in ("n", "mean", "median", "p25", "p75")
        }
    }

    five_tools = five.get("tool_usage_patterns", {}).get("calls", {})
    full_tools = full.get("tool_usage_patterns", {}).get("calls", {})
    tool_comparison = {
        name: {
            "five_tool": five_tools.get(name, 0),
            "full14": full_tools.get(name, 0),
            "delta_full14_minus_five_tool": full_tools.get(name, 0) - five_tools.get(name, 0),
        }
        for name in sorted(set(five_tools) | set(full_tools))
    }
    return {
        "status": "preserved five-tool baseline versus full 14-tool Locator reproduction",
        "five_tool_report": five.get("experiment_id"),
        "full14_report": full.get("experiment_id"),
        "same_manifest_sample_size": five.get("n") == full.get("n") == 45,
        "completion": {
            "five_tool": {key: five.get(key) for key in ("n", "completed", "completion_rate", "termination_reasons")},
            "full14": {key: full.get(key) for key in ("n", "completed", "completion_rate", "termination_reasons")},
            "delta_completion_rate_full14_minus_five_tool": _delta(full.get("completion_rate"), five.get("completion_rate")),
        },
        "metrics": metric_comparison,
        "resource_stats": stat_comparison,
        "tool_usage": tool_comparison,
        "model_metadata": {
            "five_tool": five.get("model_metadata"),
            "full14": full.get("model_metadata"),
        },
        "notes": [
            "Both reports use the same seeded 45-instance manifest and the same offline evaluator adapter.",
            "The full14 run uses the latest successful attempt when a transient API failure was retried; failed attempts remain in the run directory.",
            "Official repository metrics are containment booleans; paper metrics are set Jaccard values.",
            "The full14 run is Locator-only and is not an N2D ablation.",
        ],
    }


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Five-tool versus full 14-tool SGAgent Locator",
        "",
        "The preserved five-tool report is compared with the independent full14 run on the same seeded 45-instance manifest.",
        "",
        "## Completion",
        "",
        "| Run | Completed | Rate | Termination |",
        "|---|---:|---:|---|",
    ]
    for label in ("five_tool", "full14"):
        row = comparison["completion"][label]
        lines.append(f"| {label} | {row['completed']}/{row['n']} | {_fmt(row['completion_rate'])} | `{row['termination_reasons']}` |")
    lines += ["", "## Metrics (full14 minus five-tool)", "", "| Group / metric | Five-tool | Full14 | Delta |", "|---|---:|---:|---:|"]
    for group, metrics in comparison["metrics"].items():
        for name, values in metrics.items():
            lines.append(f"| {group} / {name} | {_fmt(values['five_tool'])} | {_fmt(values['full14'])} | {_fmt(values['delta_full14_minus_five_tool'])} |")
    lines += ["", "## Resource statistics (mean and median)", "", "| Group / metric | Five-tool mean | Full14 mean | Delta | Five-tool median | Full14 median |", "|---|---:|---:|---:|---:|---:|"]
    for group, metrics in comparison["resource_stats"].items():
        for name, values in metrics.items():
            lines.append(f"| {group} / {name} | {_fmt(values['mean']['five_tool'])} | {_fmt(values['mean']['full14'])} | {_fmt(values['mean']['delta_full14_minus_five_tool'])} | {_fmt(values['median']['five_tool'])} | {_fmt(values['median']['full14'])} |")
    lines += ["", "## Tool distribution", "", "| Tool | Five-tool | Full14 | Delta |", "|---|---:|---:|---:|"]
    for name, values in comparison["tool_usage"].items():
        lines.append(f"| `{name}` | {values['five_tool']} | {values['full14']} | {values['delta_full14_minus_five_tool']} |")
    lines += ["", "## Interpretation", ""]
    lines.extend(f"- {note}" for note in comparison["notes"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--five-report", required=True)
    parser.add_argument("--full-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    comparison = build_comparison(_load(Path(args.five_report)), _load(Path(args.full_report)))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison_report.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "comparison_report.md").write_text(write_markdown(comparison), encoding="utf-8")
    print(json.dumps({"output": str(output), "comparison": comparison}, ensure_ascii=False))


if __name__ == "__main__":
    main()
