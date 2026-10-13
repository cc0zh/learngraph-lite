"""Model-facing protocol objects used by the standalone Agent runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class TextMessage:
    role: Role
    content: str
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)


class ModelGateway(Protocol):
    """Minimal model interface; adapters live outside agent_core."""

    def complete(self, messages: tuple[TextMessage, ...], tools: tuple[dict[str, Any], ...]) -> ModelResponse:
        """Return one model response for the current conversation window."""
