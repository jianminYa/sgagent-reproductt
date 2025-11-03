"""Logging utilities"""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any


# Global storage for API statistics
api_stats: List[Dict[str, Any]] = []
api_stats_file: Optional[str] = None


def record_api_call(
    model_name: str,
    prompt: str,
    response: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None
) -> None:
    """Record API call statistics"""
    api_call_record = {
        "timestamp": datetime.now().isoformat(),
        "model_name": model_name,
        "prompt": prompt,
        "response": response,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": (prompt_tokens or 0) + (completion_tokens or 0)
    }
    api_stats.append(api_call_record)

    # Write to JSON file if path is set
    if api_stats_file:
        try:
            with open(api_stats_file, "w", encoding="utf-8") as f:
                json.dump(api_stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to write API stats to file: {e}")


def set_api_stats_file(file_path: str) -> None:
    """Set the file path for API statistics logging"""
    global api_stats_file
    api_stats_file = file_path


def get_api_stats() -> List[Dict[str, Any]]:
    """Get current API statistics"""
    return api_stats.copy()