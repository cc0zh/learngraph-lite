"""Application use cases for declarative lessons and event explanations."""

from __future__ import annotations

from dataclasses import dataclass, field

from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.application.learning import LearningService
from learngraph_lite.domain.learning.exercises import Attempt
from learngraph_lite.domain.lessons import LessonEvent, LessonPackage, ack_event, build_lesson_package


@dataclass
class LessonState:
    packages: dict[str, LessonPackage] = field(default_factory=dict)
    events: dict[str, LessonEvent] = field(default_factory=dict)
    explanation_runs: dict[tuple[str, str], str] = field(default_factory=dict)
    failed_explanations: set[tuple[str, str]] = field(default_factory=set)


@dataclass
class InMemoryLessonRepository:
    _states: dict[str, LessonState] = field(default_factory=dict)

    def state(self, goal_id: str) -> LessonState:
        return self._states.setdefault(goal_id, LessonState())


class LessonService:
    def __init__(self, repository: InMemoryLessonRepository, learning: LearningService, loop: AgentLoop):
        self._repository = repository
        self._learning = learning
        self._loop = loop

    def save_package(self, package: LessonPackage) -> LessonPackage:
        state = self._repository.state(package.goal_id)
        state.packages[package.id] = build_lesson_package(
            package_id=package.id,
            goal_id=package.goal_id,
            node_id=package.node_id,
            graph_content_revision=package.graph_content_revision,
            markdown=package.markdown,
            components=package.components,
        )
        return state.packages[package.id]

    def ack_event(self, goal_id: str, event: LessonEvent) -> LessonEvent:
        state = self._repository.state(goal_id)
        existing = state.events.get(event.id)
        if existing is not None:
            return existing
        package = state.packages.get(event.package_id)
        if package is None:
            raise ValueError("unknown lesson package")
        accepted = ack_event(package, event)
        state.events[event.id] = accepted
        return accepted

    def submit_choice_answer(self, goal_id: str, exercise_id: str, selected_option_id: str, attempt_id: str) -> Attempt:
        return self._learning.submit_answer(goal_id, exercise_id, selected_option_id, attempt_id)

    def explain_event(self, goal_id: str, event_id: str, slot: str, request_id: str) -> str:
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
        if record.status == "completed":
            state.explanation_runs[key] = record.run_id
            state.failed_explanations.discard(key)
            return record.run_id
        state.failed_explanations.add(key)
        raise RuntimeError(record.error or "explanation run failed")
