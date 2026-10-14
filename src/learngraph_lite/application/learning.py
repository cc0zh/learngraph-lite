"""Application use cases for M3 node learning, practice and recommendation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from copy import deepcopy
from threading import RLock
from typing import Callable, Protocol, TypeVar

from learngraph_lite.application.agent import AgentLoop, RunRequest
from learngraph_lite.domain.learning import GraphSnapshot, MasteryState
from learngraph_lite.domain.learning.exercises import (
    Attempt,
    ExerciseOption,
    ExercisePrivate,
    ExercisePublic,
    build_single_choice_exercise,
    judge_attempt,
)
from learngraph_lite.domain.learning.mastery import AttemptResult, score_mastery
from learngraph_lite.domain.learning.recommendations import NextAction, recommend_next_action
from learngraph_lite.domain.lessons import ComponentKind, LessonPackage

T = TypeVar("T")


@dataclass
class LearningState:
    graph: GraphSnapshot
    exercises: dict[str, ExercisePrivate] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    run_ids_by_key: dict[str, str] = field(default_factory=dict)
    final_text_by_key: dict[str, str] = field(default_factory=dict)
    generation_operations: dict[str, dict] = field(default_factory=dict)


class LearningRepository(Protocol):
    def save(self, goal_id: str, state: LearningState) -> None: ...

    def get(self, goal_id: str) -> LearningState: ...

    def mutate(self, goal_id: str, update: Callable[[LearningState], T]) -> T: ...


class StaleLearningGraphError(ValueError):
    """Learning progress belongs to a different planning snapshot."""


@dataclass
class InMemoryLearningRepository:
    _states: dict[str, LearningState] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def save(self, goal_id: str, state: LearningState) -> None:
        with self._lock:
            self._states[goal_id] = state

    def get(self, goal_id: str) -> LearningState:
        try:
            return self._states[goal_id]
        except KeyError as exc:
            raise KeyError(f"unknown learning goal: {goal_id}") from exc

    def mutate(self, goal_id: str, update: Callable[[LearningState], T]) -> T:
        with self._lock:
            state = deepcopy(self.get(goal_id))
            result = update(state)
            self._states[goal_id] = state
            return result


class LearningService:
    def __init__(self, repository: LearningRepository, loop: AgentLoop | None = None):
        self._repository = repository
        self._loop = loop

    def start_goal(self, graph: GraphSnapshot) -> None:
        self._repository.save(graph.goal_id, LearningState(graph=graph))

    def ensure_goal(self, graph: GraphSnapshot) -> None:
        """Recover publication interrupted before initial learning state was saved."""
        try:
            self._repository.get(graph.goal_id)
        except KeyError:
            self.start_goal(graph)

    def migrate_graph(self, graph: GraphSnapshot) -> bool:
        """Preserve historical artifacts; only current-version evidence is counted."""
        return self._repository.mutate(graph.goal_id, lambda state: migrate_learning_graph(state, graph))

    def validate_lesson_exercises(self, package: LessonPackage) -> None:
        state = self._repository.get(package.goal_id)
        _require_node(state.graph, package.node_id)
        if state.graph.content_revision != package.graph_content_revision:
            raise ValueError("lesson content revision is outdated")
        exercise_ids = [component.props["exercise_id"] for component in package.components
                        if component.kind == ComponentKind.QUIZ_CHOICE]
        if len(exercise_ids) > 3 or len(set(exercise_ids)) != len(exercise_ids):
            raise ValueError("lesson supports at most three unique exercises")
        for component in package.components:
            if component.kind != ComponentKind.QUIZ_CHOICE:
                continue
            exercise = state.exercises.get(component.props["exercise_id"])
            if exercise is None or (exercise.goal_id, exercise.node_id, exercise.graph_content_revision) != (
                    package.goal_id, package.node_id, package.graph_content_revision):
                raise ValueError("lesson exercise must belong to the same goal, node and content revision")

    def lesson_exercise(self, package: LessonPackage, exercise_id: str) -> ExercisePublic:
        """Read only public question content for a saved lesson's explanation input."""
        exercise = self._repository.get(package.goal_id).exercises.get(exercise_id)
        if exercise is None or (exercise.node_id, exercise.graph_content_revision) != (
                package.node_id, package.graph_content_revision):
            raise ValueError("lesson exercise does not belong to this node/content revision")
        return exercise.to_public()

    def learn_node(self, goal_id: str, node_id: str, user_text: str, request_id: str) -> str:
        if self._loop is None:
            raise RuntimeError("node learning requires an AgentLoop")
        state = self._repository.get(goal_id)
        _require_node(state.graph, node_id)
        existing = state.final_text_by_key.get(request_id)
        if existing is not None:
            return existing
        record = self._loop.run(
            RunRequest(
                session_id=f"{goal_id}:{node_id}",
                user_text=user_text,
                idempotency_key=request_id,
                goal_id=goal_id,
                node_id=node_id,
            )
        )
        def save_result(current: LearningState):
            current.run_ids_by_key.setdefault(request_id, record.run_id)
            if record.status == "completed":
                current.final_text_by_key.setdefault(request_id, record.final_text)
        self._repository.mutate(goal_id, save_result)
        return record.final_text

    def context(self, goal_id: str, node_id: str, *, expected_graph: GraphSnapshot | None = None) -> dict:
        state = self._repository.get(goal_id)
        _check_graph(state, expected_graph)
        _require_node(state.graph, node_id)
        nodes = {node.id: node for node in state.graph.nodes}

        def describe(selected_id: str) -> dict:
            mastery, samples, accuracy = _mastery(state, selected_id)
            return {
                **asdict(nodes[selected_id]), "mastery": mastery.value,
                "sample_count": samples, "accuracy": accuracy,
            }

        return {
            "goal_id": goal_id,
            "graph_revision": state.graph.revision,
            "content_revision": state.graph.content_revision,
            "graph_status": state.graph.status.value,
            "node": describe(node_id),
            "prerequisites": [describe(edge.source) for edge in state.graph.edges if edge.target == node_id],
        }

    def create_fixture_exercise(self, goal_id: str, node_id: str, exercise_id: str, prompt: str) -> ExercisePublic:
        state = self._repository.get(goal_id)
        _require_node(state.graph, node_id)
        exercise = build_single_choice_exercise(
            exercise_id=exercise_id,
            goal_id=goal_id,
            node_id=node_id,
            graph_content_revision=state.graph.content_revision,
            prompt=prompt,
            options=(
                ExerciseOption("a", "只生成没有来源的自然语言回答"),
                ExerciseOption("b", "先检索资料片段，再基于片段回答并返回引用"),
                ExerciseOption("c", "让前端自己判断答案是否可信"),
            ),
            correct_option_id="b",
            explanation="RAG 学习节点要求回答能被资料片段和引用核查。",
        )
        def save_exercise(current: LearningState):
            _check_graph(current, state.graph)
            if any(existing.normalized_hash == exercise.normalized_hash and existing.node_id == node_id
                   and existing.graph_content_revision == exercise.graph_content_revision
                   for existing in current.exercises.values()):
                raise ValueError("duplicate exercise for current node revision")
            if exercise.id in current.exercises:
                raise ValueError("exercise id already exists")
            current.exercises[exercise.id] = exercise
        self._repository.mutate(goal_id, save_exercise)
        return exercise.to_public()

    def submit_answer(self, goal_id: str, exercise_id: str, selected_option_id: str, attempt_id: str) -> Attempt:
        def submit(state: LearningState):
            exercise = state.exercises[exercise_id]
            if exercise.graph_content_revision != state.graph.content_revision:
                raise ValueError("exercise version is stale")
            existing = next((item for item in state.attempts if item.id == attempt_id), None)
            if existing is not None:
                if existing.exercise_id != exercise_id or existing.selected_option_id != selected_option_id:
                    raise ValueError("attempt id was already used for different input")
                return existing
            previous = tuple(attempt for attempt in state.attempts if attempt.exercise_id == exercise_id)
            attempt = judge_attempt(
                attempt_id=attempt_id, exercise=exercise, selected_option_id=selected_option_id,
                previous_attempts_for_exercise=previous,
            )
            state.attempts.append(attempt)
            return attempt
        return self._repository.mutate(goal_id, submit)

    def mastery(self, goal_id: str, node_id: str) -> tuple[MasteryState, int, float]:
        state = self._repository.get(goal_id)
        return _mastery(state, node_id)

    def next_action(self, goal_id: str, available_minutes: int | None = None,
                    *, expected_graph: GraphSnapshot | None = None) -> NextAction:
        state = self._repository.get(goal_id)
        _check_graph(state, expected_graph)
        mastery = {node.id: _mastery(state, node.id)[0] for node in state.graph.nodes}
        recent_wrong = tuple(attempt.node_id for attempt in state.attempts
                             if _current_attempt(state, attempt) and not attempt.is_correct)[-5:]
        return recommend_next_action(
            graph=state.graph,
            mastery_by_node=mastery,
            recent_wrong_node_ids=recent_wrong,
            available_minutes=available_minutes,
        )


def _require_node(graph: GraphSnapshot, node_id: str) -> None:
    if node_id not in {node.id for node in graph.nodes}:
        raise ValueError(f"unknown node: {node_id}")


def _check_graph(state: LearningState, expected_graph: GraphSnapshot | None) -> None:
    if expected_graph is not None and state.graph != expected_graph:
        raise StaleLearningGraphError("learning graph differs from the published planning snapshot")


def _mastery(state: LearningState, node_id: str) -> tuple[MasteryState, int, float]:
    counted = tuple(
        AttemptResult(attempt.exercise_id, attempt.is_correct)
        for attempt in state.attempts
        if attempt.node_id == node_id and _current_attempt(state, attempt)
    )
    return score_mastery(counted)


def _current_attempt(state: LearningState, attempt: Attempt) -> bool:
    exercise = state.exercises.get(attempt.exercise_id)
    return (attempt.counted and exercise is not None
            and exercise.graph_content_revision == state.graph.content_revision)


def migrate_learning_graph(state: LearningState, graph: GraphSnapshot) -> bool:
    if state.graph.goal_id != graph.goal_id:
        raise StaleLearningGraphError("learning goal scope does not match graph")
    reset = state.graph.content_revision != graph.content_revision
    state.graph = graph
    return reset
