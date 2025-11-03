"""
Find log files containing 'Workflow execution failed: Error code: 400'
and extract instance IDs to write to a target file.
"""

import typer
from pathlib import Path

app = typer.Typer()


@app.command()
def find_error_logs(
    log_dir: Path = typer.Argument(..., help="Directory containing log files"),
    output_file: Path = typer.Argument(..., help="Output file to write instance IDs"),
    error_pattern: str = typer.Option(
        "Workflow execution failed: Error code: 400", help="Error pattern to search for"
    ),
):
    """
    Traverse a directory for .log files containing error pattern
    and extract instance IDs to write to output file.

    Example:
        python find_err.py logs/deepseek-v3_round_c_1 failed_instances.txt
    """
    if not log_dir.exists():
        typer.echo(f"Error: Directory '{log_dir}' does not exist", err=True)
        raise typer.Exit(1)

    if not log_dir.is_dir():
        typer.echo(f"Error: '{log_dir}' is not a directory", err=True)
        raise typer.Exit(1)

    # Find all .log files
    log_files = list(log_dir.glob("*.log"))

    if not log_files:
        typer.echo(f"No .log files found in '{log_dir}'")
        return

    typer.echo(f"Found {len(log_files)} log files in '{log_dir}'")
    typer.echo(f"Searching for pattern: '{error_pattern}'")

    instance_ids = []

    # Process each log file
    for log_file in log_files:
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                content = f.read()

                # Check if error pattern exists in the file
                if error_pattern in content:
                    # Extract instance ID from filename
                    # Format: django__django-13710_2025-10-13_00-13-59.log
                    filename = log_file.stem  # Remove .log extension

                    # Use regex to find the date pattern and split there
                    import re

                    # Match YYYY-MM-DD pattern preceded by underscore
                    match = re.search(r"_(\d{4}-\d{2}-\d{2})", filename)

                    if match:
                        # Get everything before the date
                        date_start = match.start()
                        instance_id = filename[:date_start]
                    else:
                        instance_id = None

                    if instance_id:
                        instance_ids.append(instance_id)
                        typer.echo(
                            f"  ✓ Found error in: {log_file.name} -> {instance_id}"
                        )
                    else:
                        typer.echo(
                            f"  ⚠ Could not extract instance ID from: {log_file.name}",
                            err=True,
                        )

        except Exception as e:
            typer.echo(f"  ✗ Error reading {log_file.name}: {e}", err=True)

    # Write instance IDs to output fiweile
    if instance_ids:
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                for instance_id in instance_ids:
                    f.write(f"{instance_id}\n")

            typer.echo(
                f"\n✓ Successfully wrote {len(instance_ids)} instance IDs to '{output_file}'"
            )
            typer.echo(
                f"Instance IDs: {', '.join(instance_ids[:5])}"
                + (
                    f" ... and {len(instance_ids) - 5} more"
                    if len(instance_ids) > 5
                    else ""
                )
            )

        except Exception as e:
            typer.echo(f"Error writing to output file: {e}", err=True)
            raise typer.Exit(1)
    else:
        typer.echo("\nNo log files found containing the error pattern.")
        typer.echo(f"Output file '{output_file}' will not be created.")


if __name__ == "__main__":
    app()
