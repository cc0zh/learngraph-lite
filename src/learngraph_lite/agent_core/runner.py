"""Model-tool execution loop inspired by nanobot's Loop/Runner split."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .budget import Budget, BudgetExceeded
from .gateway import BudgetedModelGateway, budgeted
from .models import ModelGateway, TextMessage
from .tools import ToolError, ToolRegistry


@dataclass(frozen=True)
class RunnerResult:
    status: str
    messages: tuple[TextMessage, ...]
    final_text: str
    errors: tuple[str, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)


class AgentRunner:
    """Run the generic model-tool loop without importing LearnGraph code."""

    def __init__(self, model: ModelGateway, tools: ToolRegistry):
        self._model = model
        self._tools = tools

    def run(self, messages: tuple[TextMessage, ...], budget: Budget | None = None) -> RunnerResult:
        budget = budget or (self._model.budget if isinstance(self._model, BudgetedModelGateway) else Budget())
        model = budgeted(self._model, budget)
        transcript = list(messages)
        errors: list[str] = []
        usage = model.usage

        try:
            for step in range(budget.max_steps):
                budget.check_step(step)
                response = model.complete(tuple(transcript), self._tools.model_tools())
                budget.check_step(step)
                if response.content or response.tool_calls:
                    transcript.append(
                        TextMessage(
                            role="assistant",
                            content=response.content,
                            tool_calls=response.tool_calls,
                        )
                    )

                if not response.tool_calls:
                    return RunnerResult(
                        status="completed",
                        messages=tuple(transcript),
                        final_text=response.content,
                        errors=tuple(errors),
                        usage=usage,
                    )

                for call in response.tool_calls:
                    budget.take_tool_call()
                    tool = self._tools.get(call.name)
                    if tool is None:
                        error = f"unknown tool: {call.name}"
                        errors.append(error)
                        transcript.append(TextMessage(role="tool", content=error, tool_call_id=call.id))
                        continue
                    try:
                        args = json.loads(call.arguments)
                    except json.JSONDecodeError as exc:
                        error = f"invalid JSON for tool {call.name}: {exc.msg}"
                        errors.append(error)
                        transcript.append(TextMessage(role="tool", content=error, tool_call_id=call.id))
                        continue
                    if not isinstance(args, dict):
                        error = f"invalid arguments for tool {call.name}: expected a JSON object"
                        errors.append(error)
                        transcript.append(TextMessage(role="tool", content=error, tool_call_id=call.id))
                        continue
                    try:
                        result = tool.execute(args)
                    except ToolError as exc:
                        result = {"error": str(exc)}
                        errors.append(str(exc))
                    transcript.append(
                        TextMessage(
                            role="tool",
                            content=json.dumps(result, ensure_ascii=False, sort_keys=True),
                            tool_call_id=call.id,
                        )
                    )
            raise BudgetExceeded("step budget exhausted")
        except BudgetExceeded as exc:
            errors.append(str(exc))
            return RunnerResult(
                status="cancelled" if budget.cancelled else "failed",
                messages=tuple(transcript),
                final_text="",
                errors=tuple(errors),
                usage=usage,
            )
