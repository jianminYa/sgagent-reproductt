#!/usr/bin/env python3
"""
Batch runner script that executes main.py for each instance in pending.txt
"""

import os
import subprocess
import sys
from pathlib import Path


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
        "sympy": "sympy"
    }
    return mapping.get(name)


def main():
    # Read pending instances
    pending_file = Path("pending.txt")
    if not pending_file.exists():
        print("Error: pending.txt not found")
        sys.exit(1)

    with open(pending_file, 'r') as f:
        instances = [line.strip() for line in f if line.strip()]

    print(f"Found {len(instances)} instances to process")

    for i, instance_id in enumerate(instances, 1):
        project_name = _get_project_name_by_instance_id(instance_id)
        base_package = extract_base_package(project_name)

        print(f"\n[{i}/{len(instances)}] Processing: {instance_id}")
        print(f"Project: {project_name} -> Package: {base_package}")

        # Set environment variables
        env = os.environ.copy()
        env['INSTANCE_ID'] = instance_id
        env['PROJECT_NAME'] = base_package

        try:
            # Run main.py with the updated environment
            result = subprocess.run(
                [sys.executable, "main.py"],
                env=env,
                capture_output=False,
                text=True
            )

            if result.returncode == 0:
                print(f"✓ Successfully completed {instance_id}")
            else:
                print(f"✗ Failed {instance_id} (exit code: {result.returncode})")

        except KeyboardInterrupt:
            print(f"\n\nInterrupted while processing {instance_id}")
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error processing {instance_id}: {e}")

    print(f"\nBatch processing completed. Processed {len(instances)} instances.")


if __name__ == "__main__":
    main()