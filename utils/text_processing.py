"""Text processing utilities"""
import textwrap


def reindent_patch(patch: str, target_indent: int) -> str:
    """Reindent a patch to match the target indentation level"""
    dedented = textwrap.dedent(patch)
    prefix = " " * target_indent
    return "\n".join(
        prefix + line if line.strip() else "" for line in dedented.splitlines()
    )


def detect_indent_from_line(line: str) -> int:
    """Detect indentation level from a line of code"""
    return len(line) - len(line.lstrip(" "))


def process_patch(patch: str, file_path: str, line_no: int) -> str:
    """Process a patch to match the indentation of the target location"""
    with open(file_path, "r", encoding="utf-8") as f:
        target_line = f.readlines()[line_no - 1]
    target_indent = detect_indent_from_line(target_line)
    return reindent_patch(patch, target_indent)