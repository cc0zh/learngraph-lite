"""Application use cases for declarative lessons and event explanations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
import json
from threading import RLock
from typing import Callable, Protocol, TypeVar

from learngraph_lite.application.agent import AgentLoop, RunAdmissionError, RunRecord, RunRequest
from learngraph_lite.application.learning import LearningService
from learngraph_lite.domain.learning.exercises import Attempt
from learngraph_lite.domain.lessons import LessonEvent, LessonPackage, ack_event, build_lesson_package

T = TypeVar("T")


class LessonError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class LessonState:
    packages: dict[str, LessonPackage] = field(default_factory=dict)
    events: dict[str, LessonEvent] = field(default_factory=dict)
    explanation_runs: dict[tuple[str, str], str] = field(default_factory=dict)
    failed_explanations: set[tuple[str, str]] = field(default_factory=set)
    generation_operations: dict[str, dict] = field(default_factory=dict)


class LessonRepository(Protocol):
    def state(self, goal_id: str) -> LessonState: ...

    def save(self, goal_id: str, state: LessonState) -> None: ...

    def mutate(self, goal_id: str, update: Callable[[LessonState], T]) -> T: ...


@dataclass
class InMemoryLessonRepository:
    _states: dict[str, LessonState] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def state(self, goal_id: str) -> LessonState:
        with self._lock:
            return deepcopy(self._states.get(goal_id, LessonState()))

    def save(self, goal_id: str, state: LessonState) -> None:
        with self._lock:
            self._states[goal_id] = deepcopy(state)

    def mutate(self, goal_id: str, update: Callable[[LessonState], T]) -> T:
        with self._lock:
            state = deepcopy(self.state(goal_id))
            result = update(state)
            self._states[goal_id] = deepcopy(state)
            return result


class LessonService:
    def __init__(self, repository: LessonRepository, learning: LearningService, loop: AgentLoop,
                 context: Callable[[str, str], dict] | None = None):
        self._repository = repository
        self._learning = learning
        self._loop = loop
        self._context = context or learning.context

    def save_package(self, package: LessonPackage) -> LessonPackage:
        validated = build_lesson_package(
            package_id=package.id,
            goal_id=package.goal_id,
            node_id=package.node_id,
            graph_content_revision=package.graph_content_revision,
            markdown=package.markdown,
            components=package.components,
            schema_version=package.schema_version, version=package.version, title=package.title,
            source_mode=package.source_mode, citation_ids=package.citation_ids, citation_map=package.citation_map,
        )
        self._learning.validate_lesson_exercises(validated)

        def commit(state):
            existing = state.packages.get(package.id)
            if existing is not None and existing != validated:
                raise LessonError("lesson_conflict", "A saved lesson package is immutable.")
            state.packages[package.id] = validated
            return validated
        return self._repository.mutate(package.goal_id, commit)

    def ack_event(self, goal_id: str, event: LessonEvent) -> LessonEvent:
        def commit(state):
            existing = state.events.get(event.id)
            if existing is not None:
                if (existing.package_id, existing.component_id, existing.action, existing.package_version) != (
                        event.package_id, event.component_id, event.action, event.package_version):
                    raise LessonError("event_conflict", "Event ID belongs to a different component or version.")
                return existing
            package = state.packages.get(event.package_id)
            if package is None:
                raise LessonError("lesson_not_found", "Unknown lesson package.")
            current = self._context(goal_id, package.node_id)
            if current["content_revision"] != package.graph_content_revision:
                raise LessonError("outdated_lesson", "Historical lessons cannot accept new events.")
            try:
                accepted = ack_event(package, event)
            except ValueError as exc:
                raise LessonError("invalid_lesson_event", str(exc)) from exc
            state.events[event.id] = accepted
            return accepted
        return self._repository.mutate(goal_id, commit)

    def submit_choice_answer(self, goal_id: str, exercise_id: str, selected_option_id: str, attempt_id: str) -> Attempt:
        return self._learning.submit_answer(goal_id, exercise_id, selected_option_id, attempt_id)

    def submit_explanation(self, session_id: str, goal_id: str, node_id: str, event_id: str,
                           slot: str, request_id: str, retry_of_run_id: str | None = None) -> RunRecord:
        """Build input exclusively from the ACK; AgentLoop admits/links before execution."""
        if not slot.strip() or len(slot) > 128:
            raise LessonError("invalid_lesson_event", "An explanation slot is required.")
        state = self._repository.state(goal_id)
        event = state.events.get(event_id)
        if event is None:
            raise LessonError("event_not_found", "ACK the lesson event before requesting explanation.")
        package = state.packages.get(event.package_id)
        if package is None:
            raise LessonError("lesson_not_found", "Unknown lesson package.")
        if package.node_id != node_id or package.version != event.package_version:
            raise LessonError("event_conflict", "Event does not belong to this node/version.")
        if package.schema_version != 1:
            raise LessonError("outdated_lesson", "Legacy lessons are read-only.")
        if event.action not in {"request_explanation", "step_changed"}:
            raise LessonError("invalid_lesson_event", "This event does not request an explanation.")
        component = ({"kind": "markdown", "props": {"text": package.markdown}} if event.component_id == "chapter"
                     else next({"kind": item.kind.value, "props": item.props}
                               for item in package.components if item.id == event.component_id))
        summary = {"event_id": event.id, "package_id": package.id, "package_version": package.version,
                   "content_revision": package.graph_content_revision, "component_id": event.component_id,
                   "action": event.action, "payload": event.payload, "component": component,
                   "explanation_slot": slot}
        if component["kind"] == "quiz_choice":
            summary["exercise"] = asdict(self._learning.lesson_exercise(package, component["props"]["exercise_id"]))
        text = "解释以下服务端已保存的学习事件：\n" + json.dumps(summary, ensure_ascii=False, sort_keys=True)
        if retry_of_run_id is not None:
            try:
                original = self._loop.request(retry_of_run_id)
            except KeyError as exc:
                raise RunAdmissionError("invalid_retry", "Unknown explanation run.") from exc
            if (original.mode, original.session_id, original.goal_id, original.node_id,
                    original.source_event_id, original.explanation_slot) != (
                    "explanation", session_id, goal_id, node_id, event_id, slot):
                raise RunAdmissionError("invalid_retry", "Retry must keep the original explanation scope.")
            text = original.user_text
        return self._loop.submit(RunRequest(session_id=session_id, user_text=text, idempotency_key=request_id,
            mode="explanation", goal_id=goal_id, node_id=node_id, source_event_id=event_id,
            explanation_slot=slot, retry_of_run_id=retry_of_run_id))

    def explain_event(self, goal_id: str, event_id: str, slot: str, request_id: str) -> str:
        """Legacy synchronous offline demo cache; HTTP uses submit_explanation instead."""
        state = self._repository.state(goal_id)
        if event_id not in state.events:
            raise ValueError("unknown lesson event")
        key = (event_id, slot)
        previous_run_id = state.explanation_runs.get(key)
        if previous_run_id is not None and key not in state.failed_explanations:
            return previous_run_id

        record = self._loop.run(
            RunRequest(
                session_id=f"{goal_id}:lesson:{event_id}:{slot}",
                user_text=f"解释学习事件 {event_id} 的 {slot}",
                idempotency_key=f"lesson:{event_id}:{slot}:{request_id if key in state.failed_explanations else 'root'}",
            )
        )
        def save_result(current):
            if record.status == "completed":
                current.explanation_runs.setdefault(key, record.run_id)
                current.failed_explanations.discard(key)
                return current.explanation_runs[key]
            if key not in current.explanation_runs:
                current.failed_explanations.add(key)
            return None
        run_id = self._repository.mutate(goal_id, save_result)
        if run_id is not None:
            return run_id
        raise RuntimeError(record.error or "explanation run failed")
