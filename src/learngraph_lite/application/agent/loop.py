"""Outer Agent run orchestration for LearnGraph Lite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

from learngraph_lite.agent_core import AgentRunner, Budget, TextMessage


@dataclass(frozen=True)
class RunRequest:
    session_id: str
    user_text: str
    idempotency_key: str
    mode: str = "runner"


@dataclass
class RunRecord:
    run_id: str
    session_id: str
    status: str
    final_text: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentLoop:
    """Owns run admission, idempotency, budget injection and terminal state."""

    def __init__(
        self,
        runner: AgentRunner,
        direct_handlers: dict[str, Callable[[RunRequest], str]] | None = None,
    ):
        self._runner = runner
        self._direct_handlers = direct_handlers or {}
        self._records_by_key: dict[str, RunRecord] = {}

    def run(self, request: RunRequest, budget: Budget | None = None) -> RunRecord:
        existing = self._records_by_key.get(request.idempotency_key)
        if existing is not None:
            return existing

        record = RunRecord(run_id=str(uuid4()), session_id=request.session_id, status="running")
        self._records_by_key[request.idempotency_key] = record
        try:
            if request.mode in self._direct_handlers:
                record.final_text = self._direct_handlers[request.mode](request)
                record.status = "completed"
                return record

            result = self._runner.run(
                (TextMessage(role="user", content=request.user_text),),
                budget=budget or Budget(),
            )
            record.status = result.status
            record.final_text = result.final_text
            record.error = "; ".join(result.errors)
            return record
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            return record
