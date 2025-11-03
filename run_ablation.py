#!/usr/bin/env python3
"""
Ablation study runner that executes main.py without knowledge graph functionality.
Gets the ROUND setting from environment variables.
"""

import os
import subprocess
import sys
from pathlib import Path
import time


def _get_project_name_by_instance_id(id):
    return id.split("__")[0]


def extract_base_package(name: str) -> str:
    mapping = {
        "astropy": "astropy",
        "matplotlib": "matplotlib",
        "mwaskom": "seaborn",
        "pallets": "flask",
        "psf": "requests",
        "pydata": "xarray",
        "sphinx-doc": "sphinx",
        "scikit-learn": "scikit-learn",
        "pytest-dev": "pytest",
        "pylint-dev": "pylint",
        "django": "django",
        "sympy": "sympy",
    }
    return mapping.get(name, "")  # 返回空字符串而不是 None


def run_instance(instance_id, index, total):
    """Run a single instance"""
    project_name = _get_project_name_by_instance_id(instance_id)
    base_package = extract_base_package(project_name)

    # Get ROUND from environment variables
    round_value = os.environ.get("ROUND", "unknown_round")

    print(f"\n[{index}/{total}] Processing: {instance_id} with ROUND={round_value}")
    print(f"Project: {project_name} -> Package: {base_package}")

    # Set environment variables
    env = os.environ.copy()
    env["INSTANCE_ID"] = instance_id
    env["PROJECT_NAME"] = base_package

    # TODO @<hanyu> 手动
    if round_value == "deepseek-v3_round_c_1":
        env["TEST_BED"] = "/Users/hanyu/projects_1"
    elif round_value == "deepseek-v3_round_c_2":
        env["TEST_BED"] = "/Users/hanyu/projects_2"
    elif round_value == "deepseek-v3_round_c_3":
        env["TEST_BED"] = "/Users/hanyu/projects_3"
    elif round_value == "deepseek-v3_round_c_4":
        env["TEST_BED"] = "/Users/hanyu/projects_4"
    else:
        env["TEST_BED"] = "/Users/hanyu/projects"  # 默认目录

    # Disable knowledge graph functionality based on environment variable
    disable_kg = os.environ.get("DISABLE_KG", "false").lower()
    env["DISABLE_KG"] = disable_kg

    try:
        # Run main.py with the updated environment
        result = subprocess.run(
            [sys.executable, "main.py"], env=env, capture_output=False, text=True
        )

        if result.returncode == 0:
            print(f"✓ Successfully completed {instance_id} with ROUND={round_value}")
        else:
            print(
                f"✗ Failed {instance_id} with ROUND={round_value} (exit code: {result.returncode})"
            )

        return (instance_id, round_value, result.returncode == 0)

    except KeyboardInterrupt:
        print(f"\n\nInterrupted while processing {instance_id}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error processing {instance_id}: {e}")
        return (instance_id, round_value, False)


def main():
    # Get ROUND from environment variables
    round_value = os.environ.get("ROUND", "unknown_round")
    print(f"Using ROUND setting: {round_value}")

    # Determine pending file based on ROUND
    # TODO @<hanyu> 手动
    if round_value == "deepseek-v3_round_c_1":
        pending_file = Path("pending_1.txt")
    elif round_value == "deepseek-v3_round_c_2":
        pending_file = Path("pending_2.txt")
    elif round_value == "deepseek-v3_round_c_3":
        pending_file = Path("pending_3.txt")
    elif round_value == "deepseek-v3_round_c_4":
        pending_file = Path("pending_4.txt")
    else:
        pending_file = Path("pending.txt")  # fallback to default

    # Check if specific pending file exists, otherwise use default
    if not pending_file.exists():
        default_pending = Path("pending.txt")
        if default_pending.exists():
            print(f"Using default pending.txt as {pending_file} not found")
            pending_file = default_pending
        else:
            print(f"Error: Neither {pending_file} nor pending.txt found")
            sys.exit(1)

    # Read pending instances
    with open(pending_file, "r") as f:
        instances = [line.strip() for line in f if line.strip()]

    print(f"Found {len(instances)} instances to process from {pending_file}")

    # Run each instance
    results = []
    for i, instance_id in enumerate(instances, 1):
        result = run_instance(instance_id, i, len(instances))
        results.append(result)

        # Add a small delay between jobs to avoid overwhelming the system
        time.sleep(1)

    # Print summary
    successful = sum(1 for r in results if r[2])
    print(
        f"\nProcessing completed for ROUND={round_value}. {successful}/{len(results)} jobs succeeded."
    )

    # Print detailed results
    print("\nDetailed results:")
    for instance_id, round_val, success in results:
        status = "✓" if success else "✗"
        print(f"  {status} {instance_id} - {round_val}")


if __name__ == "__main__":
    main()
