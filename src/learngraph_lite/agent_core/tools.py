"""Tool abstractions for the standalone Agent runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .models import TextMessage


class ToolError(RuntimeError):
    """A tool failed in a way that should be returned to the model."""


InputModel = type[BaseModel]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]
    input_model: InputModel | None = None
    ends_turn: bool = False
    with_context: bool = False

    @classmethod
    def from_model(
        cls,
        name: str,
        description: str,
        input_model: InputModel,
        handler: Callable[..., Any],
        *, ends_turn: bool = False, with_context: bool = False,
    ) -> "Tool":
        schema = input_model.model_json_schema()
        schema["additionalProperties"] = False
        return cls(name, description, schema, handler, input_model, ends_turn, with_context)

    def as_model_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def execute(self, args: dict[str, Any], *, messages: tuple[TextMessage, ...] = ()) -> Any:
        if self.input_model is not None:
            try:
                validated = self.input_model.model_validate(args, strict=True, extra="forbid")
            except ValidationError as exc:
                raise ToolError(f"invalid arguments for tool {self.name}: {exc}") from exc
            args = validated.model_dump(mode="python")
        # Host-supplied context is never a model-editable schema parameter.
        return self.handler(args, messages) if self.with_context else self.handler(args)


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def model_tools(self) -> tuple[dict[str, Any], ...]:
        return tuple(tool.as_model_tool() for tool in self._tools.values())
