"""Freeze the official SGAgent Lite reproduction sample."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd


UPSTREAM_COMMIT = "33a2cfe61d56494ab2d20a2b0c48c1f43e37b452"
PAPER_LITE_SIZE = 300


def build_manifest(seed: int, size: int, lite_path: str | Path,
                   instance_ids: list[str] | None = None) -> dict:
    df = pd.read_parquet(lite_path)
    rows = df.sort_values(["instance_id", "repo"]).drop_duplicates("instance_id")
    all_ids = [str(value) for value in rows["instance_id"].tolist()]
    if len(all_ids) != PAPER_LITE_SIZE:
        raise ValueError(f"expected {PAPER_LITE_SIZE} Lite rows, found {len(all_ids)}")
    if size < 1 or size > len(all_ids):
        raise ValueError(f"size must be between 1 and {len(all_ids)}")
    if instance_ids is None:
        selected_ids = set(random.Random(seed).sample(all_ids, size))
        sampling = "random.Random(seed).sample(sorted Lite instance_id list)"
    else:
        selected_ids = set(instance_ids)
        unknown = selected_ids - set(all_ids)
        if unknown:
            raise ValueError(f"unknown Lite instance IDs: {sorted(unknown)}")
        if not selected_ids:
            raise ValueError("instance_ids must not be empty")
        size = len(selected_ids)
        sampling = "explicit instance IDs selected from the frozen Lite manifest for smoke testing"
    selected = rows[rows["instance_id"].isin(selected_ids)].sort_values("instance_id")
    instances = [
        {
            "instance_id": str(row.instance_id),
            "repo": str(row.repo),
            "base_commit": str(row.base_commit),
            "problem_statement": str(row.problem_statement),
        }
        for row in selected.itertuples(index=False)
    ]
    return {
        "schema_version": "1.0",
        "experiment_id": "sgagent_official_locator_reproduction",
        "dataset": {
            "name": "SWE-bench Lite",
            "benchmark_split": "test",
            "lite_path": str(Path(lite_path).resolve()),
            "source_url": "https://huggingface.co/datasets/princeton-nlp/SWE-bench",
            "source_note": "Local dataset/lite.parquet is authoritative for this reproduction run.",
            "revision": "local-commit-33a2cfe",
            "row_count": len(all_ids),
            "sort_rule": "instance_id ascending after repo de-duplication",
        },
        "sampling": {
            "seed": seed,
            "requested_size": size,
            "actual_size": len(instances),
            "method": sampling,
        },
        "official_configuration": {
            "temperature": 0.0,
            "workflow": "official create_workflow; Locator node and its official tool/summarizer transitions",
            "graph_recursion_limit": 150,
            "output_token_limit": None,
            "official_tool_source": "tools.retriever_tools",
            "official_prompt_source": "prompts.system + prompts.locator",
            "locator_sets_per_instance": 1,
            "note": "The public repository runner processes each pending instance once; paper text describes four localization sets for full repair sampling.",
        },
        "instances": instances,
        "distribution": {
            "repo": {repo: sum(item["repo"] == repo for item in instances) for repo in sorted({item["repo"] for item in instances})},
        },
        "upstream": {
            "remote": "https://github.com/iSEngLab/SGAgent.git",
            "commit": UPSTREAM_COMMIT,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--size", type=int, default=45)
    parser.add_argument("--ids", nargs="+", help="Explicit instance IDs, used for a named smoke manifest")
    parser.add_argument("--lite", default="dataset/lite.parquet")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = build_manifest(args.seed, args.size, args.lite, args.ids)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "instances": len(manifest["instances"]), "distribution": manifest["distribution"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
