"""Model-tool execution loop inspired by nanobot's Loop/Runner split."""

from __future__ import annotations

import json
from time import monotonic
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

    def run(self, messages: tuple[TextMessage, ...], budget: Budget | None = None, on_progress=None) -> RunnerResult:
        budget = budget or (self._model.budget if isinstance(self._model, BudgetedModelGateway) else Budget())
        model = budgeted(self._model, budget)
        transcript = list(messages)
        errors: list[str] = []
        usage = model.usage

        try:
            for step in range(budget.max_steps):
                budget.check_step(step)
                if on_progress is None:
                    response = model.complete(tuple(transcript), self._tools.model_tools())
                else:
                    response = model.stream_complete(tuple(transcript), self._tools.model_tools(),
                        lambda text: on_progress("message.delta", {"text": text}))
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

                for index, call in enumerate(response.tool_calls):
                    budget.take_tool_call()
                    started = monotonic()
                    if on_progress is not None:
                        on_progress("tool.started", {"call_id": call.id, "name": call.name})
                    tool = self._tools.get(call.name)
                    if tool is None:
                        error = f"unknown tool: {call.name}"
                        errors.append(error)
                        transcript.append(TextMessage(role="tool", content=error, tool_call_id=call.id))
                        if on_progress is not None:
                            on_progress("tool.finished", {"call_id": call.id, "name": call.name, "status": "failed"})
                        continue
                    try:
                        args = json.loads(call.arguments)
                    except json.JSONDecodeError as exc:
                        error = f"invalid JSON for tool {call.name}: {exc.msg}"
                        errors.append(error)
                        transcript.append(TextMessage(role="tool", content=error, tool_call_id=call.id))
                        if on_progress is not None:
                            on_progress("tool.finished", {"call_id": call.id, "name": call.name, "status": "failed"})
                        continue
                    if not isinstance(args, dict):
                        error = f"invalid arguments for tool {call.name}: expected a JSON object"
                        errors.append(error)
                        transcript.append(TextMessage(role="tool", content=error, tool_call_id=call.id))
                        if on_progress is not None:
                            on_progress("tool.finished", {"call_id": call.id, "name": call.name, "status": "failed"})
                        continue
                    try:
                        result = tool.execute(args)
                        succeeded = not (isinstance(result, dict) and "error" in result)
                    except ToolError as exc:
                        result = {"error": str(exc)}
                        errors.append(str(exc))
                        succeeded = False
                    transcript.append(
                        TextMessage(
                            role="tool",
                            content=json.dumps(result, ensure_ascii=False, sort_keys=True),
                            tool_call_id=call.id,
                        )
                    )
                    budget.check_step(0)
                    if on_progress is not None:
                        on_progress("tool.finished", {"call_id": call.id, "name": call.name,
                            "status": "failed" if isinstance(result, dict) and "error" in result else "completed",
                            "elapsed_ms": round((monotonic() - started) * 1000)})
                    if succeeded and tool.ends_turn:
                        # Pair the whole batch, without executing calls after user review.
                        for skipped in response.tool_calls[index + 1:]:
                            transcript.append(TextMessage(role="tool", tool_call_id=skipped.id,
                                content=json.dumps({"skipped": "turn ended; waiting for user review"})))
                            if on_progress is not None:
                                on_progress("tool.finished", {"call_id": skipped.id, "name": skipped.name,
                                                             "status": "skipped"})
                        return RunnerResult("completed", tuple(transcript), response.content, tuple(errors), usage)
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
