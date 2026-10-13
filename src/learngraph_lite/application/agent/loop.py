"""Outer Agent run orchestration for LearnGraph Lite."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Condition
from typing import Any, Callable
from uuid import uuid4

from learngraph_lite.agent_core import AgentRunner, Budget, TextMessage
from learngraph_lite.agent_core.budget import BudgetExceeded


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "budget_exceeded"}


class RunAdmissionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RunRequest:
    session_id: str
    user_text: str
    idempotency_key: str
    mode: str = "runner"
    goal_id: str | None = None
    node_id: str | None = None
    exercise_count: int = 1
    exercise_purpose: str = "practice"
    retry_of_run_id: str | None = None
    task_ref: str | None = None
    planning_version: int = 0
    graph_node_count: int = 10


@dataclass(frozen=True)
class DirectResult:
    final_text: str
    output: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedRun:
    runner: AgentRunner
    messages: tuple[TextMessage, ...]
    project_output: Callable[[str], dict[str, Any]] | None = None


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
    output: dict[str, Any] = field(default_factory=dict)
    goal_id: str | None = None
    node_id: str | None = None
    root_task_id: str = ""
    task_ref: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentLoop:
    """Owns run admission, idempotency, budget injection, events and terminal state."""

    def __init__(
        self,
        runner: AgentRunner,
        direct_handlers: dict[str, Callable[[RunRequest, Budget, str], DirectResult]] | None = None,
        *,
        prepare_run: Callable[[RunRequest, Budget, str], PreparedRun] | None = None,
        validate_run: Callable[[RunRequest], None] | None = None,
    ):
        self._runner = runner
        self._direct_handlers = direct_handlers or {}
        self._prepare_run = prepare_run
        self._validate_run = validate_run
        self._session_scopes: dict[str, tuple[str | None, str | None]] = {}
        self._records_by_key: dict[tuple[str, str], RunRecord] = {}
        self._requests_by_key: dict[tuple[str, str], RunRequest] = {}
        self._records_by_id: dict[str, RunRecord] = {}
        self._events_by_run: dict[str, list[RunEvent]] = {}
        self._active: dict[str, Budget] = {}
        self._condition = Condition()
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    def run(self, request: RunRequest, budget: Budget | None = None) -> RunRecord:
        with self._condition:
            record, created = self._admit(request, budget or Budget())
        if created:
            self._execute(record, request)
        return record

    def submit(self, request: RunRequest, budget: Budget | None = None) -> RunRecord:
        """Admit once and return without waiting for model/tool execution."""
        with self._condition:
            record, created = self._admit(request, budget or Budget())
            if created:
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent-run")
                self._executor.submit(self._execute, record, request)
            return _copy_record(record)

    def _admit(self, request: RunRequest, budget: Budget) -> tuple[RunRecord, bool]:
        if self._closed:
            raise RunAdmissionError("shutting_down", "application is shutting down")
        planning_task = request.mode in {"clarify", "graph"}
        if planning_task:
            if request.goal_id is None or request.node_id is not None or request.task_ref != f"goal:{request.goal_id}":
                raise RunAdmissionError("invalid_scope", "planning tasks require a goal task_ref and no node")
        elif request.task_ref is not None or (request.goal_id is None) != (request.node_id is None):
            raise RunAdmissionError("invalid_scope", "goal_id and node_id must be provided together")
        if request.mode in {"exercise", "teaching"} and request.goal_id is None:
            raise RunAdmissionError("invalid_scope", "this mode requires a goal and node")
        key = (request.session_id, request.idempotency_key)
        existing = self._records_by_key.get(key)
        if existing is not None:
            if self._requests_by_key[key] != request:
                raise RunAdmissionError("idempotency_conflict", "request ID was already used for different input")
            return existing, False
        if self._validate_run is not None:
            self._validate_run(request)
        scope = (request.goal_id, request.node_id)
        if request.session_id in self._session_scopes and self._session_scopes[request.session_id] != scope:
            raise RunAdmissionError("session_scope_conflict", "use a new session when changing goal or node")
        if any(self._records_by_id[run_id].session_id == request.session_id for run_id in self._active):
            raise RunAdmissionError("session_busy", "this session already has an active run")
        if len(self._active) >= 2:
            raise RunAdmissionError("capacity_exceeded", "at most two runs can execute at once")
        root_task_id = ""
        if request.retry_of_run_id is not None:
            previous = self._records_by_id.get(request.retry_of_run_id)
            if previous is None or previous.status not in {"failed", "cancelled", "budget_exceeded"}:
                raise RunAdmissionError("invalid_retry", "retry requires a failed or cancelled run")
            if previous.run_id in self._active:
                raise RunAdmissionError("session_busy", "previous execution has not stopped")
            original = next(value for key, value in self._requests_by_key.items()
                            if self._records_by_key[key].run_id == previous.run_id)
            if replace(original, idempotency_key=request.idempotency_key,
                       retry_of_run_id=request.retry_of_run_id) != request:
                raise RunAdmissionError("invalid_retry", "retry must keep the original session and input")
            root_task_id = previous.root_task_id
        record = RunRecord(run_id=str(uuid4()), session_id=request.session_id, status="queued",
                           goal_id=request.goal_id, node_id=request.node_id, task_ref=request.task_ref)
        record.root_task_id = root_task_id or record.run_id
        self._records_by_key[key] = record
        self._session_scopes[request.session_id] = scope
        self._requests_by_key[key] = request
        self._records_by_id[record.run_id] = record
        self._events_by_run[record.run_id] = []
        self._active[record.run_id] = budget
        return record, True

    def _execute(self, record: RunRecord, request: RunRequest) -> None:
        with self._condition:
            budget = self._active[record.run_id]
            if record.status in TERMINAL_STATUSES:
                self._release(record)
                return
            record.status = "running"
            record.updated_at = datetime.now(UTC)
            self._emit(record, "run.started", {"status": record.status, "mode": request.mode})
        try:
            budget.check_step(0)
            if request.mode in self._direct_handlers:
                result = self._direct_handlers[request.mode](request, budget, record.root_task_id)
                budget.check_step(0)
                with self._condition:
                    if record.status not in TERMINAL_STATUSES:
                        record.final_text = result.final_text
                        record.output = deepcopy(result.output)
                        record.usage = dict(result.usage)
                        self._finish(record, "completed", summary="direct generation completed")
                return

            prepared = PreparedRun(self._runner, (TextMessage(role="user", content=request.user_text),))
            if request.goal_id is not None:
                if self._prepare_run is None:
                    raise ValueError("node learning is not configured for this entry point")
                prepared = self._prepare_run(request, budget, record.root_task_id)
            result = prepared.runner.run(prepared.messages, budget=budget)
            output = {}
            if result.status == "completed" and prepared.project_output is not None and not budget.cancelled:
                output = prepared.project_output(result.final_text)
            with self._condition:
                if record.status not in TERMINAL_STATUSES:
                    record.final_text = result.final_text
                    record.error = "; ".join(result.errors)
                    record.usage = dict(result.usage)
                    record.output = deepcopy(output)
                    status = "budget_exceeded" if _is_budget_failure(result.status, result.errors) else result.status
                    self._finish(record, status, summary=_summary_for(status, record))
        except BudgetExceeded as exc:
            with self._condition:
                if record.status not in TERMINAL_STATUSES:
                    record.error = str(exc)
                    record.usage = dict(budget.usage)
                    self._finish(record, "cancelled" if budget.cancelled else "budget_exceeded", summary=str(exc))
        except Exception as exc:
            with self._condition:
                if record.status not in TERMINAL_STATUSES:
                    record.error = str(exc)
                    record.usage = dict(budget.usage)
                    self._finish(record, "failed", summary="run failed before producing a result")
        finally:
            with self._condition:
                self._release(record)

    def _release(self, record: RunRecord) -> None:
        # Cancellation ends public state, but cannot preempt a blocking provider call.
        self._active.pop(record.run_id, None)
        self._condition.notify_all()

    def get_run(self, run_id: str) -> RunRecord:
        with self._condition:
            return _copy_record(self._record(run_id))

    def _record(self, run_id: str) -> RunRecord:
        if run_id not in self._records_by_id:
            raise KeyError(f"unknown run: {run_id}")
        return self._records_by_id[run_id]

    def events(self, run_id: str, *, after_seq: int = 0) -> tuple[RunEvent, ...]:
        with self._condition:
            self._record(run_id)
            return tuple(replace(event, payload=deepcopy(event.payload))
                         for event in self._events_by_run[run_id] if event.seq > after_seq)

    def snapshot(self, run_id: str) -> tuple[RunRecord, int]:
        """Capture state and event cursor atomically for a new SSE subscriber."""
        with self._condition:
            return _copy_record(self._record(run_id)), len(self._events_by_run[run_id])

    def wait_events(self, run_id: str, after_seq: int, timeout: float) -> tuple[RunEvent, ...]:
        with self._condition:
            self._record(run_id)
            self._condition.wait_for(
                lambda: len(self._events_by_run[run_id]) > after_seq
                or self._records_by_id[run_id].status in TERMINAL_STATUSES,
                timeout=timeout,
            )
            return self.events(run_id, after_seq=after_seq)

    def cancel(self, run_id: str) -> RunRecord:
        with self._condition:
            record = self._record(run_id)
            if record.status not in TERMINAL_STATUSES:
                self._active[run_id].cancelled = True
                self._finish(record, "cancelled", summary="run was cancelled before completion")
            return _copy_record(record)

    def close(self) -> None:
        """Stop admission, cooperatively cancel and join the bounded worker pool."""
        with self._condition:
            self._closed = True
            for run_id in tuple(self._active):
                self.cancel(run_id)
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True)

    def _finish(self, record: RunRecord, status: str, *, summary: str) -> None:
        if record.status in TERMINAL_STATUSES:
            return
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
        if record.output:
            payload["output"] = deepcopy(record.output)
        self._emit(record, f"run.{status}", payload)

    def _emit(self, record: RunRecord, event_type: str, payload: dict[str, Any]) -> None:
        events = self._events_by_run[record.run_id]
        events.append(RunEvent(run_id=record.run_id, seq=len(events) + 1, type=event_type, payload=payload))
        self._condition.notify_all()


def _copy_record(record: RunRecord) -> RunRecord:
    return replace(record, usage=dict(record.usage), output=deepcopy(record.output))


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
