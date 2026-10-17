"""Outer Agent run orchestration for LearnGraph Lite."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Condition
from typing import Any, Callable, Protocol
from uuid import uuid4

from learngraph_lite.agent_core import AgentRunner, Budget, TextMessage
from learngraph_lite.agent_core.budget import BudgetExceeded
from learngraph_lite.application.lifecycle import DeletedScope


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "budget_exceeded", "interrupted"}


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
    lesson_purpose: str = "学习当前节点"
    lesson_exercise_ids: tuple[str, ...] = ()
    source_event_id: str | None = None
    explanation_slot: str | None = None
    stream: bool = False
    proposal_purpose: str = "改进学习路线"
    graph_feedback: str = ""
    response_to_run_id: str | None = None
    planning_answers_json: str = ""
    parent_session_id: str | None = None


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
    prepare_history: Callable[[tuple[TextMessage, ...]], tuple[TextMessage, ...]] | None = None


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
    user_text: str = ""
    mode: str = "runner"
    partial_text: str = ""
    tool_activity: dict[str, dict] = field(default_factory=dict)
    protocol_messages: list[dict] = field(default_factory=list)
    response_to_run_id: str | None = None


class RunRepository(Protocol):
    def deleted_identities(self) -> tuple[frozenset[str], frozenset[str]]: ...

    def load(self) -> tuple[tuple[RunRequest, RunRecord, tuple[RunEvent, ...]], ...]: ...

    def admit(self, request: RunRequest, record: RunRecord) -> None: ...

    def save(self, record: RunRecord, events: tuple[RunEvent, ...]) -> None: ...


class AgentLoop:
    """Owns run admission, idempotency, budget injection, events and terminal state."""

    def __init__(
        self,
        runner: AgentRunner,
        direct_handlers: dict[str, Callable[[RunRequest, Budget, str], DirectResult]] | None = None,
        *,
        prepare_run: Callable[[RunRequest, Budget, str], PreparedRun] | None = None,
        validate_run: Callable[[RunRequest], None] | None = None,
        repository: RunRepository | None = None,
    ):
        self._runner = runner
        self._direct_handlers = direct_handlers or {}
        self._prepare_run = prepare_run
        self._validate_run = validate_run
        self._repository = repository
        self._session_scopes: dict[str, tuple[str | None, str | None]] = {}
        self._records_by_key: dict[tuple[str, str], RunRecord] = {}
        self._requests_by_key: dict[tuple[str, str], RunRequest] = {}
        self._records_by_id: dict[str, RunRecord] = {}
        self._events_by_run: dict[str, list[RunEvent]] = {}
        self._active: dict[str, Budget] = {}
        self._condition = Condition()
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False
        self._explanation_roots: dict[tuple[str, str, str], str] = {}
        self._deleted_sessions: set[str] = set()
        self._deleted_goals: set[str] = set()
        if repository is not None:
            sessions, goals = repository.deleted_identities()
            self._deleted_sessions.update(sessions)
            self._deleted_goals.update(goals)
            for request, record, events in repository.load():
                self._register(request, record, events)
            with self._condition:
                for record in self._records_by_id.values():
                    if record.status not in TERMINAL_STATUSES:
                        self._finish(record, "interrupted", summary="previous process stopped; retry explicitly",
                                     error="execution interrupted by process restart")

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
        if (request.session_id in self._deleted_sessions or request.parent_session_id in self._deleted_sessions
                or request.goal_id in self._deleted_goals):
            raise RunAdmissionError("scope_deleted", "This conversation or goal was deleted; create a new identity.")
        if request.parent_session_id == request.session_id:
            raise RunAdmissionError("invalid_scope", "A child session cannot be its own parent.")
        for previous in self._requests_by_key.values():
            if previous.session_id == request.session_id and previous.parent_session_id != request.parent_session_id:
                raise RunAdmissionError("session_scope_conflict", "A session cannot change its parent conversation.")
        planning_task = request.mode in {"planning", "clarify", "graph", "proposal"}
        if planning_task:
            if request.goal_id is None or request.node_id is not None or request.task_ref != f"goal:{request.goal_id}":
                raise RunAdmissionError("invalid_scope", "planning tasks require a goal task_ref and no node")
        elif request.task_ref is not None or (request.goal_id is None) != (request.node_id is None):
            raise RunAdmissionError("invalid_scope", "goal_id and node_id must be provided together")
        if request.mode in {"exercise", "lesson", "teaching", "explanation"} and request.goal_id is None:
            raise RunAdmissionError("invalid_scope", "this mode requires a goal and node")
        explaining = request.source_event_id is not None and request.explanation_slot is not None
        if (request.mode == "explanation") != explaining or ((request.source_event_id is None) != (request.explanation_slot is None)):
            raise RunAdmissionError("invalid_scope", "explanations require an event and slot")
        key = (request.session_id, request.idempotency_key)
        existing = self._records_by_key.get(key)
        if existing is not None:
            if self._requests_by_key[key] != request:
                raise RunAdmissionError("idempotency_conflict", "request ID was already used for different input")
            return existing, False
        if request.mode == "planning" and request.session_id != f"planning:{request.goal_id}":
            raise RunAdmissionError("invalid_scope", "planning uses the goal planning session")
        if request.mode != "planning" and (request.response_to_run_id is not None or request.planning_answers_json):
            raise RunAdmissionError("invalid_scope", "question card responses require planning mode")
        if request.response_to_run_id is not None:
            retry_root = self._records_by_id.get(request.retry_of_run_id) if request.retry_of_run_id else None
            for prior_key, prior in self._requests_by_key.items():
                if prior.response_to_run_id == request.response_to_run_id:
                    record = self._records_by_key[prior_key]
                    if retry_root is None or record.root_task_id != retry_root.root_task_id:
                        raise RunAdmissionError("planning_response_used", "Question card was already answered; retry the original task explicitly.")
        if explaining and request.retry_of_run_id is None:
            root = self._explanation_roots.get((request.goal_id, request.source_event_id, request.explanation_slot))
            if root is not None:
                original = self.request(root)
                if (original.session_id, original.node_id, original.user_text) != (request.session_id, request.node_id, request.user_text):
                    raise RunAdmissionError("idempotency_conflict", "explanation input differs from the saved task")
                attempts = [record for record in self._records_by_id.values() if record.root_task_id == root]
                return max(attempts, key=lambda record: record.created_at), False
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
            if previous is None or previous.status not in {"failed", "cancelled", "budget_exceeded", "interrupted"}:
                raise RunAdmissionError("invalid_retry", "retry requires a failed or cancelled run")
            if previous.run_id in self._active:
                raise RunAdmissionError("session_busy", "previous execution has not stopped")
            original = next(value for key, value in self._requests_by_key.items()
                            if self._records_by_key[key].run_id == previous.run_id)
            if replace(original, idempotency_key=request.idempotency_key,
                       retry_of_run_id=request.retry_of_run_id) != request:
                raise RunAdmissionError("invalid_retry", "retry must keep the original session and input")
            root_task_id = previous.root_task_id
            if any(record.root_task_id == root_task_id and record.status == "completed"
                   for record in self._records_by_id.values()):
                raise RunAdmissionError("invalid_retry", "this task already has a completed run")
        record = RunRecord(run_id=str(uuid4()), session_id=request.session_id, status="queued",
                           goal_id=request.goal_id, node_id=request.node_id, task_ref=request.task_ref,
                           user_text=request.user_text if request.mode in {"runner", "teaching", "planning"} else "", mode=request.mode,
                           response_to_run_id=request.response_to_run_id)
        record.root_task_id = root_task_id or record.run_id
        if self._repository is not None:
            try:
                self._repository.admit(request, record)
            except RunAdmissionError:
                raise
            except Exception as exc:
                raise RunAdmissionError("storage_unavailable", "run admission could not be persisted") from exc
        self._register(request, record, ())
        self._active[record.run_id] = budget
        return record, True

    def _register(self, request: RunRequest, record: RunRecord, events: tuple[RunEvent, ...]) -> None:
        key = (request.session_id, request.idempotency_key)
        scope = (request.goal_id, request.node_id)
        self._records_by_key[key] = record
        self._session_scopes[request.session_id] = scope
        self._requests_by_key[key] = request
        self._records_by_id[record.run_id] = record
        self._events_by_run[record.run_id] = list(events)
        if request.source_event_id is not None and record.root_task_id == record.run_id:
            self._explanation_roots[(request.goal_id, request.source_event_id, request.explanation_slot)] = record.run_id

    def _execute(self, record: RunRecord, request: RunRequest) -> None:
        with self._condition:
            budget = self._active[record.run_id]
            if record.status in TERMINAL_STATUSES:
                self._release(record)
                return
        try:
            with self._condition:
                self._emit(record, "run.started", {"status": "running", "mode": request.mode}, status="running")
            budget.check_step(0)
            if request.mode in self._direct_handlers:
                result = self._direct_handlers[request.mode](request, budget, record.root_task_id)
                budget.check_step(0)
                with self._condition:
                    if record.status not in TERMINAL_STATUSES:
                        self._finish(record, "completed", summary="direct generation completed",
                                     final_text=result.final_text, output=deepcopy(result.output), usage=dict(result.usage))
                return

            prepared = PreparedRun(self._runner, (TextMessage(role="user", content=request.user_text),))
            if request.goal_id is not None:
                if self._prepare_run is None:
                    raise ValueError("node learning is not configured for this entry point")
                prepared = self._prepare_run(request, budget, record.root_task_id)
            with self._condition:
                history = []
                for previous in self.list_runs(request.session_id)[-8:]:
                    if previous.run_id != record.run_id and previous.status == "completed" and previous.mode == request.mode:
                        from learngraph_lite.agent_core.models import ToolCall
                        for item in previous.protocol_messages:
                            history.append(TextMessage(**{**item, "tool_calls": tuple(ToolCall(**c) for c in item.get("tool_calls", ())) }))
            if prepared.prepare_history is not None:
                history = prepared.prepare_history(tuple(history))
            messages = (*prepared.messages[:-1], *history, prepared.messages[-1])
            result = prepared.runner.run(messages, budget=budget,
                on_progress=(lambda kind, data: self._progress(record, kind, data)) if request.stream else None)
            output = {}
            if result.status == "completed" and prepared.project_output is not None and not budget.cancelled:
                output = prepared.project_output(result.final_text)
            with self._condition:
                if record.status not in TERMINAL_STATUSES:
                    status = "budget_exceeded" if _is_budget_failure(result.status, result.errors) else result.status
                    error = "; ".join(result.errors)
                    self._finish(record, status, summary=_summary_for(status, replace(record, error=error)),
                                 final_text=result.final_text, error=error, usage=dict(result.usage), output=deepcopy(output),
                                 protocol_messages=[{**asdict(m), "tool_calls": [asdict(c) for c in m.tool_calls]}
                                                    for m in result.messages[len(messages)-1:]] if status == "completed" else [])
        except BudgetExceeded as exc:
            with self._condition:
                if record.status not in TERMINAL_STATUSES:
                    self._finish(record, "cancelled" if budget.cancelled else "budget_exceeded", summary=str(exc),
                                 error=str(exc), usage=dict(budget.usage))
        except Exception as exc:
            with self._condition:
                if record.status not in TERMINAL_STATUSES:
                    self._finish(record, "failed", summary="run failed before producing a result",
                                 error=str(exc), usage=dict(budget.usage))
        finally:
            with self._condition:
                self._release(record)

    def _release(self, record: RunRecord) -> None:
        # Cancellation ends public state, but cannot preempt a blocking provider call.
        self._active.pop(record.run_id, None)
        self._condition.notify_all()

    def _progress(self, record: RunRecord, kind: str, payload: dict) -> None:
        # Token events are volatile; terminal snapshots persist text and safe tool state.
        with self._condition:
            if record.status in TERMINAL_STATUSES:
                return
            if kind == "message.delta":
                record.partial_text = (record.partial_text + payload["text"])[-65536:]
            elif kind.startswith("tool."):
                record.tool_activity[payload["call_id"]] = {**record.tool_activity.get(payload["call_id"], {}),
                    **payload, "status": payload.get("status", "running")}
            events = self._events_by_run[record.run_id]
            event = RunEvent(record.run_id, self._cursor(record.run_id) + 1, kind, deepcopy(payload))
            if len(events) >= 512:
                del events[0]
            events.append(event)
            self._condition.notify_all()

    def _cursor(self, run_id: str) -> int:
        events = self._events_by_run[run_id]
        return events[-1].seq if events else 0

    def get_run(self, run_id: str) -> RunRecord:
        with self._condition:
            return _copy_record(self._record(run_id))

    def request(self, run_id: str) -> RunRequest:
        with self._condition:
            self._record(run_id)
            return next(request for key, request in self._requests_by_key.items()
                        if self._records_by_key[key].run_id == run_id)

    def list_runs(self, session_id: str) -> tuple[RunRecord, ...]:
        with self._condition:
            return tuple(_copy_record(record) for record in sorted(self._records_by_id.values(),
                         key=lambda record: record.created_at) if record.session_id == session_id)

    def list_all_runs(self) -> tuple[RunRecord, ...]:
        """Return a read-only snapshot for conversation discovery, including old scopes."""
        with self._condition:
            return tuple(_copy_record(record) for record in sorted(self._records_by_id.values(),
                         key=lambda record: record.created_at))

    def delete_scope(self, commit: Callable[[], DeletedScope], *, session_id: str | None = None,
                     goal_id: str | None = None) -> None:
        """Serialize deletion with admission; public cancellation is not worker exit.

        The durable callback must commit atomically or raise. Memory changes only
        after its success, while admission and worker transitions remain excluded.
        """
        with self._condition:
            sessions = {session_id} if session_id is not None else {f"planning:{goal_id}"}
            if goal_id is not None:
                sessions.update(record.session_id for record in self._records_by_id.values()
                                if record.goal_id == goal_id)
            while True:
                children = {request.session_id for request in self._requests_by_key.values()
                            if request.parent_session_id in sessions}
                if children <= sessions:
                    break
                sessions.update(children)
            runs = {record.run_id for record in self._records_by_id.values()
                    if record.session_id in sessions or (goal_id is not None and record.goal_id == goal_id)}
            if runs.intersection(self._active):
                raise RunAdmissionError("session_busy", "Execution has not stopped; wait for workers to exit before deleting.")
            deleted = commit()
            sessions.update(deleted.session_ids)
            runs.update(deleted.run_ids)
            self._deleted_sessions.update(sessions)
            if goal_id is not None:
                self._deleted_goals.add(goal_id)
            for key, record in tuple(self._records_by_key.items()):
                if record.run_id in runs:
                    del self._records_by_key[key]
                    del self._requests_by_key[key]
            for run_id in runs:
                self._records_by_id.pop(run_id, None)
                self._events_by_run.pop(run_id, None)
            for session in sessions:
                self._session_scopes.pop(session, None)
            self._explanation_roots = {key: root for key, root in self._explanation_roots.items() if root not in runs}
            self._condition.notify_all()

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
            return _copy_record(self._record(run_id)), self._cursor(run_id)

    def wait_events(self, run_id: str, after_seq: int, timeout: float) -> tuple[RunEvent, ...]:
        with self._condition:
            self._record(run_id)
            self._condition.wait_for(
                lambda: run_id not in self._records_by_id or self._cursor(run_id) > after_seq
                or self._records_by_id[run_id].status in TERMINAL_STATUSES,
                timeout=timeout,
            )
            if run_id not in self._records_by_id:
                return ()
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

    def _finish(self, record: RunRecord, status: str, *, summary: str, **changes) -> None:
        if record.status in TERMINAL_STATUSES:
            return
        candidate = replace(record, status=status, summary=summary, **changes)
        payload: dict[str, Any] = {"status": status, "summary": summary}
        if candidate.final_text:
            payload["final_text"] = candidate.final_text
        if candidate.error:
            payload["error"] = candidate.error
        if candidate.usage:
            payload["usage"] = dict(candidate.usage)
        if candidate.output:
            payload["output"] = deepcopy(candidate.output)
        self._emit(record, f"run.{status}", payload, status=status, summary=summary, **changes)

    def _emit(self, record: RunRecord, event_type: str, payload: dict[str, Any], **changes) -> None:
        events = self._events_by_run[record.run_id]
        candidate = replace(record, updated_at=datetime.now(UTC), **changes)
        event = RunEvent(run_id=record.run_id, seq=self._cursor(record.run_id) + 1, type=event_type, payload=payload)
        if self._repository is not None:
            try:
                self._repository.save(candidate, (*events, event))
            except Exception as exc:
                # Keep the durable previous state for restart recovery. The live process
                # stops admission rather than reporting an unpersisted success.
                self._closed = True
                record.status = "interrupted"
                record.error = "run state could not be persisted; restart after repairing storage"
                record.summary = "storage unavailable"
                record.updated_at = datetime.now(UTC)
                events.append(RunEvent(record.run_id, self._cursor(record.run_id) + 1, "run.interrupted",
                                       {"status": record.status, "error": record.error}))
                self._condition.notify_all()
                raise RunAdmissionError("storage_unavailable", record.error) from exc
        record.__dict__.update(candidate.__dict__)
        events.append(event)
        self._condition.notify_all()


def _copy_record(record: RunRecord) -> RunRecord:
    return deepcopy(record)


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
