"""Deterministic fake-LLM integration test for both arms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage


@dataclass
class FakeLLM:
    """Return a scripted sequence without making a network request."""

    responses: list[Any]
    calls: int = 0

    def bind_tools(self, tools: Any) -> "FakeLLM":
        return self

    def invoke(self, messages: Any) -> Any:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, AIMessage):
            return response
        return AIMessage(content=response)
