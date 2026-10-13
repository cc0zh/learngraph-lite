"""Outer Agent run orchestration for LearnGraph Lite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from learngraph_lite.agent_core import AgentRunner, Budget, TextMessage


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "budget_exceeded"}


@dataclass(frozen=True)
class RunRequest:
    session_id: str
    user_text: str
    idempotency_key: str
    mode: str = "runner"


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class RunRecord:
    run_id: str
    session_id: str
    status: str
    final_text: str = ""
    error: str = ""
    summary: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentLoop:
    """Owns run admission, idempotency, budget injection, events and terminal state."""

    def __init__(
        self,
        runner: AgentRunner,
        direct_handlers: dict[str, Callable[[RunRequest], str]] | None = None,
    ):
        self._runner = runner
        self._direct_handlers = direct_handlers or {}
        self._records_by_key: dict[str, RunRecord] = {}
        self._records_by_id: dict[str, RunRecord] = {}
        self._events_by_run: dict[str, list[RunEvent]] = {}

    def run(self, request: RunRequest, budget: Budget | None = None) -> RunRecord:
        existing = self._records_by_key.get(request.idempotency_key)
        if existing is not None:
            return existing

        record = RunRecord(run_id=str(uuid4()), session_id=request.session_id, status="running")
        self._records_by_key[request.idempotency_key] = record
        self._records_by_id[record.run_id] = record
        self._events_by_run[record.run_id] = []
        self._emit(record, "run.started", {"status": record.status, "mode": request.mode})
        try:
            if request.mode in self._direct_handlers:
                record.final_text = self._direct_handlers[request.mode](request)
                self._finish(record, "completed", summary="direct generation completed")
                return record

            result = self._runner.run(
                (TextMessage(role="user", content=request.user_text),),
                budget=budget or Budget(),
            )
            record.final_text = result.final_text
            record.error = "; ".join(result.errors)
            record.usage = dict(result.usage)
            status = "budget_exceeded" if _is_budget_failure(result.status, result.errors) else result.status
            self._finish(record, status, summary=_summary_for(status, record))
            return record
        except Exception as exc:
            record.error = str(exc)
            self._finish(record, "failed", summary="run failed before producing a result")
            return record

    def get_run(self, run_id: str) -> RunRecord:
        try:
            return self._records_by_id[run_id]
        except KeyError as exc:
            raise KeyError(f"unknown run: {run_id}") from exc

    def events(self, run_id: str, *, after_seq: int = 0) -> tuple[RunEvent, ...]:
        if run_id not in self._records_by_id:
            raise KeyError(f"unknown run: {run_id}")
        return tuple(event for event in self._events_by_run[run_id] if event.seq > after_seq)

    def cancel(self, run_id: str) -> RunRecord:
        record = self.get_run(run_id)
        if record.status in TERMINAL_STATUSES:
            return record
        self._finish(record, "cancelled", summary="run was cancelled before completion")
        return record

    def _finish(self, record: RunRecord, status: str, *, summary: str) -> None:
        record.status = status
        record.summary = summary
        record.updated_at = datetime.now(UTC)
        payload: dict[str, Any] = {"status": status, "summary": summary}
        if record.final_text:
            payload["final_text"] = record.final_text
        if record.error:
            payload["error"] = record.error
        if record.usage:
            payload["usage"] = dict(record.usage)
        self._emit(record, f"run.{status}", payload)

    def _emit(self, record: RunRecord, event_type: str, payload: dict[str, Any]) -> None:
        events = self._events_by_run[record.run_id]
        events.append(RunEvent(run_id=record.run_id, seq=len(events) + 1, type=event_type, payload=payload))


def _is_budget_failure(status: str, errors: tuple[str, ...]) -> bool:
    if status != "failed":
        return False
    return any("budget exhausted" in error for error in errors)


def _summary_for(status: str, record: RunRecord) -> str:
    if status == "completed":
        return "run completed"
    if status == "cancelled":
        return record.error or "run was cancelled"
    if status == "budget_exceeded":
        return record.error or "run stopped after reaching its budget"
    return record.error or "run failed"
