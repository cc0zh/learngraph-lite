"""Execution budget primitives for the standalone Agent runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


@dataclass
class Budget:
    """Small deterministic budget shared by model calls and tool calls."""

    max_model_calls: int = 6
    max_tool_calls: int = 12
    max_steps: int = 8
    max_input_tokens: int = 12000
    max_seconds: float = 120.0
    started: float = field(default_factory=monotonic)
    cancelled: bool = False
    model_calls: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=dict)

    def check_step(self, step: int) -> None:
        if self.cancelled:
            raise BudgetExceeded("run was cancelled")
        if monotonic() - self.started >= self.max_seconds:
            raise BudgetExceeded("deadline budget exhausted")
        if step >= self.max_steps:
            raise BudgetExceeded("step budget exhausted")

    def take_model_call(self) -> None:
        self.check_step(0)
        if self.model_calls >= self.max_model_calls:
            raise BudgetExceeded("model call budget exhausted")
        self.model_calls += 1

    def take_tool_call(self) -> None:
        self.check_step(0)
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded("tool call budget exhausted")
        self.tool_calls += 1


class BudgetExceeded(RuntimeError):
    """Raised when a run cannot continue within its configured budget."""
